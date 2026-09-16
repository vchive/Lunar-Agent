"""Prepare an ordinary bundle profile from a frozen evaluator and the parent's input ledger."""
from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from ._benchmark_files import absolute_path, read_regular_file
from ._candidate_workspace_io import DirectoryChain
from .algorithm import AlgorithmProblemContract
from .budget import BudgetSpec
from .bundle_evolution import load_bundle_pipeline
from .candidate_evaluation_spec import CandidateEvaluationSpec, canonical_json, strict_json
from .candidate_execution import CandidateExecutionInput, _inputs
from .data_profile import DataProfileError, build_private_input_profile
from .evaluator import MAX_ARTIFACT_BYTES
from .evaluator_bundle import (
    BUNDLE_FILES,
    COMPILED_BUNDLE_EVALUATOR_ID,
    compile_evaluator_bundle,
    load_evaluator_bundle,
)
from .evolution import CandidateInputArtifact, EvolutionError
from .models import RunStatus
from .solve_bundle import (
    bundle_pipeline_sha256,
    prepare_solve_bundle_pipeline,
    validate_solve_bundle_inputs,
)

_PROFILE = "bundle-profile.json"
_EVENT = "bundle_profile_prepared"
_ENVIRONMENT = {
    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8",
}
_MAX_PROFILE_BYTES = 128 * 1024
_MAX_FROZEN_FILE_BYTES = 512 * 1024


def _fail(reason="invalid"):
    raise EvolutionError("automatic_bundle_" + reason)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _present(path):
    return path.exists() or path.is_symlink()


def _parent(store, parent_id, contract=None):
    parent = store.get_run(parent_id)
    if parent is None:
        _fail("parent_missing")
    if parent.status == RunStatus.CANCELLED:
        _fail("cancelled")
    plan = store.get_current_plan(parent_id)
    current = AlgorithmProblemContract.from_dict(plan.algorithm_problem) if plan and plan.algorithm_problem else None
    if contract is not None and (current is None or current.digest() != contract.digest()):
        _fail("contract_mismatch")
    return parent, current


def _descriptors(store, parent, contract=None):
    descriptors = {}
    for row in store.list_artifacts(parent.id):
        if row.get("kind") != "input_data":
            continue
        descriptor = CandidateInputArtifact(row.get("path"), row.get("size"), row.get("sha256"))
        if row.get("run_id", parent.id) != parent.id or descriptors.get(descriptor.path, descriptor) != descriptor:
            _fail("inputs_invalid")
        descriptors[descriptor.path] = descriptor
    if contract is not None and set(descriptors) != {"data/raw/" + item.path for item in contract.inputs}:
        _fail("inputs_invalid")
    concrete = _inputs(tuple(CandidateExecutionInput(
        item.path.removeprefix("data/raw/"), "parent-input", item.size, item.sha256,
    ) for item in descriptors.values()))
    contents = {item.target: read_regular_file(absolute_path(parent.workspace) / "data/raw" / item.target,
                                             item.size, exact_size=True) for item in concrete}
    validate_solve_bundle_inputs(store, parent.id, contents)
    ordered = tuple(descriptors[path] for path in sorted(descriptors))
    try:
        profile = build_private_input_profile(Path(parent.workspace), contract, ordered) if contract is not None else None
    except DataProfileError:
        _fail("inputs_invalid")
    return ordered, concrete, profile


def _profile_payload(bundle, concrete, contract, timeout):
    python = str(Path(sys.executable).resolve())
    source = read_regular_file(bundle.root / "evaluator.py", _MAX_FROZEN_FILE_BYTES)
    evaluator = CandidateEvaluationSpec(
        _sha(source), len(source), (python, "-I"), evaluator_id=COMPILED_BUNDLE_EVALUATOR_ID,
        environment=_ENVIRONMENT, timeout_seconds=timeout,
        max_output_file_bytes=MAX_ARTIFACT_BYTES,
        max_total_output_bytes=MAX_ARTIFACT_BYTES * len(contract.outputs),
    )
    return {
        "schema_version": "1", "protocol": "lunar-bundle-pipeline-v1",
        "evaluator": evaluator.to_dict(), "harness_path": "evaluator-bundle/evaluator.py",
        "input_root": "data/raw", "inputs": [item.to_dict() for item in concrete],
        "command": [python], "environment": dict(_ENVIRONMENT), "timeout_seconds": timeout,
        "max_output_bytes": 64 * 1024,
        "dependency_sha256": _sha(b"lunar-automatic-bundle-python-standard-library-v1"),
        "environment_sha256": _sha(canonical_json({
            "protocol": "lunar-automatic-bundle-environment-v1", "environment": _ENVIRONMENT,
        })),
    }


def _event(store, parent):
    event_id = "event-bundle-profile-prepared-" + _sha(parent.id.encode())
    matching = [item for item in store.list_events(parent.id)
                if item.get("type") == _EVENT or item.get("id") == event_id]
    if not matching:
        return event_id, None
    if (len(matching) != 1 or matching[0].get("type") != _EVENT
            or matching[0].get("id") != event_id or matching[0].get("task_id") is not None
            or not isinstance(matching[0].get("payload"), dict)):
        _fail("prepared_invalid")
    return event_id, matching[0]["payload"]


def _has_child(store, parent):
    child_root = absolute_path(parent.workspace) / "evolution-run"
    return (_present(child_root) or store.get_run_by_workspace(child_root) is not None
            or any(item["type"] == "evolution_linked" for item in store.list_events(parent.id)))


def _materials(bundle, profile):
    result = {"evaluator-bundle/" + name: read_regular_file(bundle.root / name, _MAX_FROZEN_FILE_BYTES)
              for name in sorted(BUNDLE_FILES)}
    result[_PROFILE] = profile
    return result


def _artifact_rows(store, parent, materials, *, register=False):
    tasks = store.list_tasks(parent.id)
    if not tasks:
        _fail("owner_missing")
    owner = tasks[0].id
    result = []
    rows = store.list_artifacts(parent.id)
    for path, content in sorted(materials.items()):
        kind = "bundle_profile" if path == _PROFILE else "evaluator_bundle"
        matches = [row for row in rows if row.get("path") == path]
        if not matches and register:
            store.add_artifact(parent.id, owner, path, _sha(content), len(content), kind)
            matches = [row for row in store.list_artifacts(parent.id) if row.get("path") == path]
        if not matches:
            continue
        if (len(matches) != 1 or matches[0].get("task_id") != owner
                or matches[0].get("kind") != kind or type(matches[0].get("size")) is not int
                or matches[0]["size"] != len(content) or matches[0].get("sha256") != _sha(content)):
            _fail("artifact_mismatch")
        result.append({key: matches[0][key] for key in ("id", "task_id", "path", "size", "sha256", "kind")})
    return result


def _budget(store, parent, materials):
    current, _ = _parent(store, parent.id)
    if current.workspace != parent.workspace:
        _fail("workspace_changed")
    known = _artifact_rows(store, parent, materials)
    paths = {row["path"] for row in known}
    rows = store.list_artifacts(parent.id)
    if any(type(row.get("size")) is not int or row["size"] < 0 for row in rows):
        _fail("artifact_mismatch")
    needed = sum(row["size"] for row in rows) + sum(len(content) for path, content in materials.items() if path not in paths)
    if needed > (current.budget or BudgetSpec()).max_artifact_bytes:
        _fail("budget_exceeded")


def _payload(parent, contract, bundle, pipeline, raw, rows):
    return {
        "schema_version": "1", "parent_run_id": parent.id, "contract_sha256": contract.digest(),
        "bundle_profile_sha256": bundle_pipeline_sha256(pipeline),
        "profile_sha256": _sha(raw), "profile_size": len(raw),
        "evaluator_bundle_sha256": bundle.fingerprint, "artifacts": rows,
    }


def _read_preparation(store, parent, contract, *, expected_timeout=None, require_event=True):
    root = absolute_path(parent.workspace)
    held = DirectoryChain(root, "automatic_bundle_workspace_invalid")
    try:
        _, concrete, input_profile = _descriptors(store, parent, contract)
        raw = read_regular_file(root / _PROFILE, _MAX_PROFILE_BYTES)
        value = strict_json(raw)
        if not isinstance(value, dict) or "timeout_seconds" not in value:
            _fail("profile_invalid")
        timeout = value["timeout_seconds"]
        if expected_timeout is not None and timeout != expected_timeout:
            _fail("settings_mismatch")
        bundle = load_evaluator_bundle(root / "evaluator-bundle", contract, input_profile=input_profile,
                                       timeout=timeout, invocation="snapshot")
        expected = canonical_json(_profile_payload(bundle, concrete, contract, timeout))
        if raw != expected:
            _fail("profile_mismatch")
        pipeline = prepare_solve_bundle_pipeline(store, parent.id, load_bundle_pipeline(root / _PROFILE))
        materials = _materials(bundle, raw)
        rows = _artifact_rows(store, parent, materials)
        _budget(store, parent, materials)
        _, event = _event(store, parent)
        if require_event and (event is None or len(rows) != len(materials)
                              or canonical_json(event) != canonical_json(_payload(parent, contract, bundle, pipeline, raw, rows))):
            _fail("prepared_mismatch")
        held.check()
        return pipeline, bundle, raw, materials
    finally:
        held.close()


def validate_automatic_solve_bundle(store, parent_id: str) -> None:
    """Read-only continuation check; an unfinished intake has no preparation to validate yet."""
    try:
        parent, contract = _parent(store, parent_id)
        _, event = _event(store, parent)
        root = absolute_path(parent.workspace)
        if event is not None:
            if contract is None:
                _fail("contract_missing")
            _read_preparation(store, parent, contract)
            return
        if _has_child(store, parent):
            _fail("prepared_missing")
        _descriptors(store, parent, contract)
        if _present(root / _PROFILE):
            if contract is None:
                _fail("contract_missing")
            _read_preparation(store, parent, contract, require_event=False)
        elif _present(root / "evaluator-bundle"):
            if contract is None:
                _fail("contract_missing")
            if any(row.get("path") == _PROFILE for row in store.list_artifacts(parent.id)):
                _fail("profile_missing")
            _, _, profile = _descriptors(store, parent, contract)
            load_evaluator_bundle(root / "evaluator-bundle", contract, input_profile=profile, invocation="snapshot")
        elif any(row.get("kind") in {"bundle_profile", "evaluator_bundle"} for row in store.list_artifacts(parent.id)):
            _fail("prepared_missing")
    except (AttributeError, KeyError, OSError, TypeError, ValueError, RecursionError):
        _fail()


@contextmanager
def _locked(root):
    held = DirectoryChain(root, "automatic_bundle_workspace_invalid")
    lock = None
    try:
        lock = os.open(".bundle-profile.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                       0o600, dir_fd=held.fd)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("lock_invalid")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("busy")
        named = os.stat(".bundle-profile.lock", dir_fd=held.fd, follow_symlinks=False)
        if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
            _fail("lock_invalid")
        yield held
        held.check()
    finally:
        try:
            if lock is not None:
                os.close(lock)
        finally:
            held.close()


def _write_profile(held, root, raw):
    if _present(root / _PROFILE):
        if read_regular_file(root / _PROFILE, len(raw), exact_size=True) != raw:
            _fail("profile_mismatch")
        return
    name = ".bundle-profile-" + secrets.token_hex(12)
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=held.fd)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                _fail("profile_write_failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.link(name, _PROFILE, src_dir_fd=held.fd, dst_dir_fd=held.fd, follow_symlinks=False)
        os.fsync(held.fd)
    finally:
        try:
            os.close(descriptor)
        finally:
            os.unlink(name, dir_fd=held.fd)
    if read_regular_file(root / _PROFILE, len(raw), exact_size=True) != raw:
        _fail("profile_mismatch")


def prepare_automatic_solve_bundle(controller, parent_id: str, contract: AlgorithmProblemContract, *, timeout_seconds: float = 900.0):
    """Compile once, freeze and pin a regular pipeline before any child candidate is created."""
    try:
        parent, _ = _parent(controller.store, parent_id, contract)
        if not contract.outputs:
            _fail("outputs_required")
        if type(timeout_seconds) not in {int, float}:
            _fail("settings_invalid")
        timeout = float(timeout_seconds)
        if not 0 < timeout <= 86400:
            _fail("settings_invalid")
        validate_automatic_solve_bundle(controller.store, parent_id)
        _, event = _event(controller.store, parent)
        if event is not None:
            return _read_preparation(controller.store, parent, contract, expected_timeout=timeout)[0]
        root = absolute_path(parent.workspace)
        with _locked(root) as held:
            parent, _ = _parent(controller.store, parent_id, contract)
            validate_automatic_solve_bundle(controller.store, parent_id)
            _, event = _event(controller.store, parent)
            if event is not None:
                return _read_preparation(controller.store, parent, contract, expected_timeout=timeout)[0]
            descriptors, concrete, input_profile = _descriptors(controller.store, parent, contract)
            bundle = compile_evaluator_bundle(controller.runtime, contract, root, inputs=descriptors,
                                              timeout=timeout, invocation="snapshot")
            current = _descriptors(controller.store, parent, contract)
            if current != (descriptors, concrete, input_profile):
                _fail("inputs_changed")
            raw = canonical_json(_profile_payload(bundle, concrete, contract, timeout))
            materials = _materials(bundle, raw)
            _budget(controller.store, parent, materials)
            _write_profile(held, root, raw)
            pipeline, bundle, raw, materials = _read_preparation(
                controller.store, parent, contract, expected_timeout=timeout, require_event=False,
            )
            rows = _artifact_rows(controller.store, parent, materials, register=True)
            held.check()
            _parent(controller.store, parent_id, contract)
            _budget(controller.store, parent, materials)
            payload = _payload(parent, contract, bundle, pipeline, raw, rows)
            event_id, _ = _event(controller.store, parent)
            controller.store.append_event(parent.id, _EVENT, payload, event_id=event_id)
            return _read_preparation(controller.store, parent, contract, expected_timeout=timeout)[0]
    except (AttributeError, KeyError, OSError, TypeError, ValueError, RecursionError):
        _fail()
