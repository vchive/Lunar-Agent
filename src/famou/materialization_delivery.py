"""Continue verified delivery from committed execution without launching another candidate."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from .artifacts import ArtifactError
from .evolution import (
    CandidateExecution,
    EvolutionError,
    _fsync_directory_chain,
    _strict_json_loads,
)
from .materialization_execution import (
    DIRECTORY as EXECUTION_DIRECTORY,
)
from .materialization_execution import (
    _digest,
    _encode,
    _path,
    _present,
    _read,
    _root,
    _sync,
    _sync_file,
    _write_record,
    inspect_materialization_execution,
)
from .materialization_launch import inspect_launch_intent
from .materialization_publication import (
    inspect_materialization_result,
    publish_materialization_result,
    recover_materialization_result,
)
from .models import Run
from .output_publication import OutputPublicationUncertain, recover_output_batch
from .store import Store

DIRECTORY = "evolution/materialization/.delivery-publication"
MAX_PLAN_BYTES = 64 * 1024
_INVALID = "materialization_delivery_evidence_invalid"


class MaterializationDeliveryUncertain(EvolutionError):
    """Retain the plan; uncertain publication must not become a new outcome."""


def delivery_authority(store: Store, parent: Run, child: Run, identity: dict) -> tuple[dict, CandidateExecution, dict]:
    intent = inspect_launch_intent(store, child, identity)
    execution = inspect_materialization_execution(store, parent, child, identity)
    if intent is None or execution is None or identity["parent_run_id"] != parent.id:
        raise MaterializationDeliveryUncertain(_INVALID)
    journal = _read(_path(_root(child), EXECUTION_DIRECTORY + "/journal.json"), 4096)
    return intent, execution, {
        "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
        "task_id": identity["task_id"], "launch_intent_sha256": _digest(_encode(intent)),
        "execution_journal_sha256": _digest(journal), "execution_sha256": _digest(_encode(execution.to_dict())),
    }


def _load(store: Store, parent: Run, child: Run, identity: dict) -> tuple[dict, str]:
    intent, execution, authority = delivery_authority(store, parent, child, identity)
    directory = _path(_root(child), DIRECTORY)
    content = _read(_path(directory, "plan.json"), MAX_PLAN_BYTES)
    plan = _strict_json_loads(content)
    if (not isinstance(plan, dict) or set(plan) != {*authority, "result", "outputs"}
        or any(plan.get(key) != value for key, value in authority.items()) or _encode(plan) != content):
        raise MaterializationDeliveryUncertain(_INVALID)
    temporary = _path(directory, ".plan.json.tmp")
    if _present(temporary) and _read(temporary, MAX_PLAN_BYTES) != content:
        raise MaterializationDeliveryUncertain(_INVALID)
    if not store.materialization_delivery_recorded(parent.id, child.id, identity["task_id"], intent, execution.to_dict(), plan):
        raise MaterializationDeliveryUncertain(_INVALID)
    return plan, _digest(content)


def inspect_materialization_delivery(store: Store, parent: Run, child: Run, identity: dict) -> dict | None:
    """Read an exact plan or prove the absence of modern delivery preparation."""
    try:
        if not _present(_path(_root(child), DIRECTORY)):
            if store.has_materialization_delivery(parent.id, child.id):
                raise MaterializationDeliveryUncertain(_INVALID)
            return None
        return _load(store, parent, child, identity)[0]
    except (MaterializationDeliveryUncertain, OutputPublicationUncertain):
        raise
    except Exception as exc:
        raise MaterializationDeliveryUncertain(_INVALID) from exc


def _no_downstream(parent: Run, child: Run) -> None:
    root = _root(child)
    for name in ("result.json", ".result.json.tmp", ".terminal-publication", ".terminal-publication.lock"):
        if _present(_path(root, "evolution/materialization/" + name)):
            raise MaterializationDeliveryUncertain(_INVALID)
    if _present(Path(parent.workspace).expanduser()) and _present(_path(
        _root(parent), ".evolved-output-publications/" + _digest(f"{parent.id}\0{child.id}".encode()),
    )):
        raise MaterializationDeliveryUncertain(_INVALID)


def _completion(directory: Path, digest: str) -> dict | None:
    found = None
    for name in ("completed.json", ".completed.json.tmp"):
        path = _path(directory, name)
        if not _present(path):
            continue
        content = _read(path, 4096)
        value = _strict_json_loads(content)
        if (not isinstance(value, dict) or set(value) != {"plan_sha256", "result_sha256", "result_size"}
            or value["plan_sha256"] != digest or _encode(value) != content
            or not isinstance(value["result_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["result_sha256"]) is None
            or type(value["result_size"]) is not int or not 0 < value["result_size"] <= MAX_PLAN_BYTES
            or (found is not None and value != found)):
            raise MaterializationDeliveryUncertain(_INVALID)
        found = value
    return found


def _completion_payload(digest: str, payload: dict) -> dict:
    content = _encode(payload)
    return {"plan_sha256": digest, "result_sha256": _digest(content), "result_size": len(content)}


def _write_complete(directory: Path, digest: str, payload: dict) -> None:
    expected = _completion_payload(digest, payload)
    current = _completion(directory, digest)
    if current is not None and current != expected:
        raise MaterializationDeliveryUncertain(_INVALID)
    path = _path(directory, "completed.json")
    if _present(path):
        _sync_file(path)
        _sync(directory)
    else:
        _write_record(directory, "completed.json", _encode(expected))


def _metadata(outputs: list | tuple) -> list[dict]:
    return [{key: value for key, value in output.items() if key != "artifact_id"} for output in outputs]


def finish_materialization_delivery(
    store: Store, parent: Run, child: Run, identity: dict, execution: CandidateExecution, *,
    specs: tuple, build_plan: Callable[[], dict], promote: Callable[[], tuple],
    validate: Callable[[dict], None], sanitize: Callable[[Exception], str],
) -> dict:
    """Prepare or resume delivery while the caller holds the child lifecycle lock."""
    try:
        return _finish(store, parent, child, identity, execution, specs, build_plan, promote, validate, sanitize)
    except (MaterializationDeliveryUncertain, OutputPublicationUncertain):
        raise
    except Exception as exc:
        raise MaterializationDeliveryUncertain(_INVALID) from exc


def _finish(store, parent, child, identity, execution, specs, build_plan, promote, validate, sanitize):
    plan = inspect_materialization_delivery(store, parent, child, identity)
    root = _root(child)
    directory = _path(root, DIRECTORY)
    if plan is None:
        intent, recorded, authority = delivery_authority(store, parent, child, identity)
        if _encode(recorded.to_dict()) != _encode(execution.to_dict()):
            raise MaterializationDeliveryUncertain(_INVALID)
        _no_downstream(parent, child)
        plan = build_plan()
        content = _encode(plan)
        if len(content) > MAX_PLAN_BYTES or any(plan.get(key) != value for key, value in authority.items()):
            raise MaterializationDeliveryUncertain(_INVALID)
        # The absent probe also rejects advanced ledger evidence before filesystem writes.
        if store.materialization_delivery_recorded(parent.id, child.id, identity["task_id"], intent, execution.to_dict(), plan):
            raise MaterializationDeliveryUncertain(_INVALID)
        for output in plan["outputs"]:
            source = _path(root, identity["attempt_path"] + "/" + output["path"])
            _sync_file(source)
            _fsync_directory_chain(source.parent, root, error="materialization_delivery_sync_failed")
        if _encode(build_plan()) != content:
            raise MaterializationDeliveryUncertain(_INVALID)
        directory.mkdir(mode=0o700)
        _sync(directory.parent)
        _write_record(directory, "plan.json", content)
        _fsync_directory_chain(directory, root, error="materialization_delivery_sync_failed")
        try:
            store.record_materialization_delivery(parent.id, child.id, identity["task_id"], intent, execution.to_dict(), plan)
        except Exception as exc:
            if not store.materialization_delivery_recorded(parent.id, child.id, identity["task_id"], intent, execution.to_dict(), plan):
                raise MaterializationDeliveryUncertain("materialization_delivery_not_prepared") from exc
    plan, digest = _load(store, parent, child, identity)
    if _encode(build_plan()) != _encode(plan):
        raise MaterializationDeliveryUncertain(_INVALID)
    completion = _completion(directory, digest)

    def terminal_check(payload):
        if _load(store, parent, child, identity) != (plan, digest) or _encode(build_plan()) != _encode(plan):
            raise MaterializationDeliveryUncertain(_INVALID)
        base = plan["result"]
        if any(_encode(payload.get(key)) != _encode(value) for key, value in base.items()
               if key not in {"status", "error", "outputs"}):
            raise MaterializationDeliveryUncertain(_INVALID)
        status, outputs = recover_output_batch(
            store, parent, child.id, specs, expected_outputs=plan["outputs"], reconcile=False,
        )
        if base["status"] == "failed":
            if _encode(payload) != _encode(base) or status is not None:
                raise MaterializationDeliveryUncertain(_INVALID)
        elif payload.get("status") == "succeeded":
            if (payload.get("error") is not None or _metadata(payload.get("outputs", [])) != plan["outputs"]
                or (bool(plan["outputs"]) and (status != "committed" or list(outputs) != payload["outputs"]))
                or (not plan["outputs"] and status is not None)):
                raise MaterializationDeliveryUncertain(_INVALID)
        elif (payload.get("status") != "failed" or payload.get("outputs")
              or not isinstance(payload.get("error"), str) or not payload["error"]
              or status not in {None, "rolled_back"}):
            raise MaterializationDeliveryUncertain(_INVALID)
        validate(payload)

    if completion is not None:
        complete = inspect_materialization_result(store, parent, child, validate=terminal_check)
        if complete is None or _completion_payload(digest, complete) != completion:
            raise MaterializationDeliveryUncertain(_INVALID)
    # Terminal preparation is inspected before allowing output recovery to mutate anything.
    payload = recover_materialization_result(store, parent, child, validate=terminal_check)
    if payload is None:
        if completion is not None:
            raise MaterializationDeliveryUncertain(_INVALID)
        for name in ("result.json", ".result.json.tmp"):
            if _present(_path(root, "evolution/materialization/" + name)):
                raise MaterializationDeliveryUncertain(_INVALID)
        status, outputs = recover_output_batch(store, parent, child.id, specs, expected_outputs=plan["outputs"])
        payload = _strict_json_loads(_encode(plan["result"]))
        if payload["status"] == "succeeded":
            failure = None
            if status is None and plan["outputs"]:
                try:
                    promote()
                except OutputPublicationUncertain:
                    raise
                except (ArtifactError, EvolutionError, OSError, TypeError, ValueError) as exc:
                    failure = sanitize(exc)
                status, outputs = recover_output_batch(store, parent, child.id, specs, expected_outputs=plan["outputs"])
                if status is None and failure is None:
                    raise MaterializationDeliveryUncertain(_INVALID)
            if status == "committed":
                payload["outputs"] = list(outputs)
            elif status == "rolled_back":
                payload.update(status="failed", outputs=[], error="output_publication_rolled_back")
            elif failure is not None:
                payload.update(status="failed", outputs=[], error=failure)
            elif plan["outputs"]:
                raise MaterializationDeliveryUncertain(_INVALID)
        elif status is not None:
            raise MaterializationDeliveryUncertain(_INVALID)
        payload = publish_materialization_result(store, parent, child, payload, validate=terminal_check)
    _write_complete(directory, digest, payload)
    terminal_check(payload)
    if _completion(directory, digest) != _completion_payload(digest, payload):
        raise MaterializationDeliveryUncertain(_INVALID)
    return payload
