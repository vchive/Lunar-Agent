"""Publish an already scored bundle to its solve parent, without executing candidate code."""
from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from . import _benchmark_files as files
from ._candidate_workspace_io import DirectoryChain
from .algorithm import AlgorithmProblemContract
from .budget import BudgetSpec
from .bundle_delivery import (
    bundle_delivery_manifest,
    inspect_bundle_delivery,
    publish_bundle_delivery,
)
from .candidate_evaluation_spec import canonical_json
from .evaluator import MAX_ARTIFACT_BYTES, Evaluation
from .evolution import EvolutionError, StrategyResult
from .models import RunStatus
from .output_publication import (
    OutputPublicationError,
    OutputPublicationUncertain,
    publish_outputs,
    recover_output_batch,
)
from .solve_bundle import validate_solve_bundle_inputs

_ROOT = ".bundle-deliveries"
_PREPARED = "bundle_delivery_prepared"
_TERMINAL = "bundle_candidate_delivered"
_MAX_RECORD_BYTES = 128 * 1024


def _fail(code="invalid"):
    raise EvolutionError("bundle_parent_delivery_" + code)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _event_id(event_type, parent_id, child_id):
    return "event-" + event_type.replace("_", "-") + "-" + _sha(f"{parent_id}\0{child_id}".encode())


def _event(controller, parent, child, event_type, expected=None):
    event_id = _event_id(event_type, parent.id, child.id)
    matching = [event for event in controller.store.list_events(parent.id)
                if event.get("id") == event_id or (
                    event.get("type") == event_type and isinstance(event.get("payload"), dict)
                    and event["payload"].get("evolution_run_id") == child.id)]
    if not matching:
        return None
    if len(matching) != 1 or matching[0].get("id") != event_id or matching[0].get("type") != event_type:
        _fail("event_mismatch")
    event = matching[0]
    payload = event.get("payload")
    if event.get("task_id") is not None or not isinstance(payload, dict):
        _fail("event_mismatch")
    canonical_json(payload, maximum=_MAX_RECORD_BYTES)
    if expected is not None and canonical_json(payload, maximum=_MAX_RECORD_BYTES) != canonical_json(expected, maximum=_MAX_RECORD_BYTES):
        _fail("event_mismatch")
    return payload


def _append(controller, parent, child, event_type, payload):
    canonical_json(payload, maximum=_MAX_RECORD_BYTES)
    existing = _event(controller, parent, child, event_type, payload)
    if existing is None:
        controller.store.append_event(
            parent.id, event_type, payload, event_id=_event_id(event_type, parent.id, child.id),
        )
    if _event(controller, parent, child, event_type, payload) is None:
        _fail("event_missing")


def _validated(controller, parent_id, child_id, contract, result=None):
    if not isinstance(contract, AlgorithmProblemContract) or (result is not None and not isinstance(result, StrategyResult)):
        _fail()
    parent, child = controller.store.get_run(parent_id), controller.store.get_run(child_id)
    if parent is None or child is None or parent_id == child_id:
        _fail("links_invalid")
    if parent.status == RunStatus.CANCELLED:
        _fail("cancelled")
    if parent.status != RunStatus.SUCCEEDED or child.status != RunStatus.SUCCEEDED:
        _fail("run_not_ready")
    actual = controller._algorithm_contract(parent)
    if actual is None or actual.digest() != contract.digest():
        _fail("contract_mismatch")
    parent_events = controller.store.list_events(parent.id)
    if any(event.get("type") == "bundle_profile_prepared" or (
        event.get("type") == "evolution_requested" and isinstance(event.get("payload"), dict)
        and event["payload"].get("bundle_mode") == "compiled"
    ) for event in parent_events):
        from .automatic_solve_bundle import validate_automatic_solve_bundle

        validate_automatic_solve_bundle(controller.store, parent.id)
    expected_child = files.absolute_path(parent.workspace) / "evolution-run"
    child_root = files.absolute_path(child.workspace)
    for root in (expected_child, child_root):
        held = DirectoryChain(root, "bundle_parent_delivery_workspace_invalid")
        held.close()
    if not expected_child.samefile(child_root):
        _fail("workspace_mismatch")
    expected_links = (
        (parent, "evolution_linked", {
            "evolution_run_id": child.id, "contract_sha256": contract.digest(), "strategy": "population",
        }),
        (child, "evolution_parent_linked", {"parent_run_id": parent.id, "contract_sha256": contract.digest()}),
    )
    for run, kind, expected in expected_links:
        links = [event for event in controller.store.list_events(run.id) if event.get("type") == kind]
        if not links or any(event.get("payload") != expected for event in links):
            _fail("links_invalid")
    identity, materials, canonical = controller._verified_bundle_evolution_delivery(child.id)
    if identity["contract_sha256"] != contract.digest() or (result is not None and
            canonical_json(result.to_dict()) != canonical_json(canonical.to_dict())):
        _fail("selection_mismatch")
    validate_solve_bundle_inputs(controller.store, parent.id, {
        path.removeprefix("inputs/"): content for path, content in materials.items() if path.startswith("inputs/")
    })
    tasks = controller.store.list_tasks(parent.id)
    owner = next((task for task in tasks if (task.plan_task_id or task.id) in {"solve", "solver"}), tasks[0] if tasks else None)
    if owner is None:
        _fail("owner_missing")
    return parent, child, identity, materials, canonical, owner.id


def _outputs(controller, parent, contract, materials, *, check_targets=True):
    prepared = []
    rows = controller.store.list_artifacts(parent.id)
    for spec in contract.outputs:
        content = materials.get(spec.path)
        if content is None:
            if spec.required:
                _fail("output_missing")
            continue
        if len(content) > MAX_ARTIFACT_BYTES:
            _fail("output_too_large")
        prepared.append((spec, content))
        if not check_targets:
            continue
        target = controller._confined_output_target(Path(parent.workspace), spec.path)
        matching = [row for row in rows if row.get("path") == spec.path and row.get("kind") == "output"]
        if len(matching) > 1 or any(row.get("size") != len(content) or row.get("sha256") != _sha(content) for row in matching):
            _fail("output_conflict")
        if target.exists() or target.is_symlink():
            if files.read_regular_file(target, len(content), exact_size=True) != content:
                _fail("output_conflict")
        elif matching:
            _fail("output_conflict")
    return prepared


def _output_metadata(prepared):
    return [{"path": spec.path, "format": spec.format, "fields": list(spec.fields),
             "required": spec.required, "size": len(content), "sha256": _sha(content)}
            for spec, content in prepared]


def _copy_manifest(identity, materials):
    return bundle_delivery_manifest(identity=identity, materials=materials)


def _budget(controller, parent, materials, identity, prepared, package_path=None):
    rows = controller.store.list_artifacts(parent.id)
    if any(type(row.get("size")) is not int or row["size"] < 0 for row in rows):
        _fail("artifact_invalid")
    copying = {**materials, "delivery.json": _copy_manifest(identity, materials)}
    additional = sum(len(content) for name, content in copying.items() if package_path is None or not any(
        row.get("path") == package_path + "/" + name for row in rows
    ))
    additional += sum(len(content) for spec, content in prepared if not any(
        row.get("path") == spec.path and row.get("kind") == "output" for row in rows
    ))
    limit = (parent.budget or BudgetSpec()).max_artifact_bytes
    if sum(row["size"] for row in rows) + additional > limit:
        _fail("budget_exceeded")
    return limit


@contextmanager
def _locked(parent):
    root = files.absolute_path(parent.workspace)
    chain = DirectoryChain(root, "bundle_parent_delivery_workspace_invalid")
    lock = None
    held = None
    try:
        try:
            os.mkdir(_ROOT, 0o700, dir_fd=chain.fd)
            os.fsync(chain.fd)
        except FileExistsError:
            pass
        held = DirectoryChain(root / _ROOT, "bundle_parent_delivery_workspace_invalid")
        lock = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=held.fd)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("lock_invalid")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("busy")
        named = os.stat(".lock", dir_fd=held.fd, follow_symlinks=False)
        if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
            _fail("lock_invalid")
        yield root / _ROOT
        held.check()
        chain.check()
    finally:
        active = sys.exc_info()[0] is not None
        failure = None
        for close in ((lambda: os.close(lock)) if lock is not None else None,
                      held.close if held is not None else None, chain.close):
            if close is not None:
                try:
                    close()
                except OSError as exc:
                    failure = failure or exc
        if failure is not None and not active:
            raise failure


def _prepared(controller, parent, child, identity, materials):
    payload = _event(controller, parent, child, _PREPARED)
    if payload is None:
        return None
    if set(payload) != {"schema_version", "parent_run_id", "evolution_run_id", "identity", "delivery_path", "delivery_sha256"}:
        _fail("prepared_invalid")
    relative = payload["delivery_path"]
    if (payload["schema_version"] != "1" or payload["parent_run_id"] != parent.id
            or payload["evolution_run_id"] != child.id or payload["identity"] != identity
            or not isinstance(relative, str) or len(Path(relative).parts) != 2
            or Path(relative).parts[0] != _ROOT or not Path(relative).name.startswith(".bundle-delivery-")):
        _fail("prepared_invalid")
    copied = inspect_bundle_delivery(Path(parent.workspace) / relative, expected_delivery_sha256=payload["delivery_sha256"])
    if copied.digest() != _sha(_copy_manifest(identity, materials)):
        _fail("copy_mismatch")
    return copied


def _kind(name):
    if name == "delivery.json":
        return "bundle_delivery_manifest"
    if name == "evaluation/report.json":
        return "bundle_evaluation_report"
    return "bundle_source" if name.startswith("source/") else "bundle_delivery_file"


def _artifacts(controller, parent, owner, copied, materials, *, register):
    root = Path(parent.workspace)
    all_files = {**materials, "delivery.json": copied._manifest}
    for name, content in sorted(all_files.items()):
        relative = (copied.delivery_path / name).relative_to(root).as_posix()
        rows = [row for row in controller.store.list_artifacts(parent.id) if row.get("path") == relative]
        if not rows and register:
            controller.store.add_artifact(parent.id, owner, relative, _sha(content), len(content), _kind(name))
            rows = [row for row in controller.store.list_artifacts(parent.id) if row.get("path") == relative]
        if len(rows) != 1 or any(row.get("task_id") != owner or row.get("sha256") != _sha(content)
                                 or row.get("size") != len(content) or row.get("kind") != _kind(name) for row in rows):
            _fail("artifact_mismatch")


def _payload(parent, child, identity, result, copied, outputs, error=None):
    relative = copied.delivery_path.relative_to(Path(parent.workspace)).as_posix()
    return {
        "schema_version": "1", "mode": "bundle", "status": "failed" if error else "succeeded",
        "parent_run_id": parent.id, "evolution_run_id": child.id, **identity,
        "candidate_path": result.best_candidate_path, "delivery_path": relative,
        "delivery_sha256": copied.digest(), "source_path": relative + "/source",
        "evaluation_report_path": relative + "/evaluation/report.json", "observation": "evaluation-time",
        "validation": Evaluation(True, tuple(item["path"] for item in outputs),
                                 "Selected outputs passed independent bundle evaluation",
                                 {"kind": "output", "evaluation_sha256": identity["evaluation_sha256"]}).as_dict(),
        "outputs": list(outputs), "error": error,
    }


def _inspect_terminal(controller, parent, child, contract, identity, materials, result, owner, copied):
    terminal = _event(controller, parent, child, _TERMINAL)
    if terminal is None:
        return None
    prepared = _outputs(controller, parent, contract, materials, check_targets=False)
    status, outputs = recover_output_batch(
        controller.store, parent, child.id, tuple(spec for spec, _ in prepared),
        expected_outputs=_output_metadata(prepared), reconcile=False,
    )
    error = "output_publication_rolled_back" if status == "rolled_back" else None
    if status not in {"committed", "rolled_back"} and prepared:
        _fail("publication_incomplete")
    expected = _payload(parent, child, identity, result, copied, () if error else outputs, error)
    if canonical_json(terminal, maximum=_MAX_RECORD_BYTES) != canonical_json(expected, maximum=_MAX_RECORD_BYTES):
        _fail("event_mismatch")
    _artifacts(controller, parent, owner, copied, materials, register=False)
    return terminal


def inspect_bundle_parent_delivery(controller, parent_id, child_id, contract):
    """Validate completed parent delivery without repair, allocation or execution."""
    parent, child, identity, materials, result, owner = _validated(controller, parent_id, child_id, contract)
    copied = _prepared(controller, parent, child, identity, materials)
    if copied is None:
        _fail("prepared_missing")
    result = _inspect_terminal(controller, parent, child, contract, identity, materials, result, owner, copied)
    if result is None:
        _fail("terminal_missing")
    return result


def finish_bundle_parent_delivery(controller, parent_id, child_id, contract, result):
    """Reuse a pinned copy and the existing output journal after an interrupted publication."""
    parent, child, identity, materials, result, owner = _validated(controller, parent_id, child_id, contract, result)
    copied = _prepared(controller, parent, child, identity, materials)
    prepared = _outputs(controller, parent, contract, materials)
    package_path = copied.delivery_path.relative_to(Path(parent.workspace)).as_posix() if copied else None
    _budget(controller, parent, materials, identity, prepared, package_path)
    with _locked(parent) as destination:
        parent, child, identity, materials, result, owner = _validated(controller, parent_id, child_id, contract, result)
        copied = _prepared(controller, parent, child, identity, materials)
        if copied is not None:
            terminal = _inspect_terminal(controller, parent, child, contract, identity, materials, result, owner, copied)
            if terminal is not None:
                return terminal
        elif _event(controller, parent, child, _TERMINAL) is not None:
            _fail("prepared_missing")
        prepared = _outputs(controller, parent, contract, materials)
        package_path = copied.delivery_path.relative_to(Path(parent.workspace)).as_posix() if copied else None
        limit = _budget(controller, parent, materials, identity, prepared, package_path)
        if copied is None:
            recover_output_batch(controller.store, parent, child.id, tuple(spec for spec, _ in prepared),
                                 expected_outputs=_output_metadata(prepared), reconcile=False)
            copied = publish_bundle_delivery(destination, identity=identity, materials=materials)
            _append(controller, parent, child, _PREPARED, {
                "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
                "identity": identity, "delivery_path": copied.delivery_path.relative_to(Path(parent.workspace)).as_posix(),
                "delivery_sha256": copied.digest(),
            })
        _artifacts(controller, parent, owner, copied, materials, register=True)
        parent, child, identity, materials, result, owner = _validated(controller, parent_id, child_id, contract, result)
        limit = _budget(controller, parent, materials, identity, prepared,
                        copied.delivery_path.relative_to(Path(parent.workspace)).as_posix())
        error = None
        try:
            outputs = publish_outputs(controller.store, parent, child.id, owner, prepared, limit)
        except OutputPublicationUncertain:
            raise
        except OutputPublicationError:
            status, _ = recover_output_batch(
                controller.store, parent, child.id, tuple(spec for spec, _ in prepared),
                expected_outputs=_output_metadata(prepared), reconcile=False,
            )
            if status != "rolled_back":
                raise
            outputs, error = (), "output_publication_rolled_back"
        payload = _payload(parent, child, identity, result, copied, outputs, error)
        _validated(controller, parent_id, child_id, contract, result)
        _prepared(controller, parent, child, identity, materials)
        _append(controller, parent, child, _TERMINAL, payload)
        return _inspect_terminal(controller, parent, child, contract, identity, materials, result, owner, copied)
