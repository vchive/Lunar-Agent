"""Read retained acceptance evidence without executing models, candidates or evaluators."""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from campaign import CAMPAIGN_ID, HERE, MANIFEST, REPO, sha, write_new
from case import INPUT_BYTES, holdouts, independent_output, validate_generated_contract

from famou._benchmark_files import read_regular_file
from famou._candidate_workspace_io import DirectoryChain
from famou.algorithm import AlgorithmProblemContract
from famou.automatic_solve_bundle import (
    automatic_bundle_preparation_status,
    validate_automatic_solve_bundle,
)
from famou.bundle_delivery import inspect_bundle_delivery
from famou.candidate_evaluation_spec import (
    canonical_json,
    parse_candidate_evaluation_spec,
    strict_json,
)
from famou.evaluator_bundle import load_evaluator_bundle
from famou.evaluator_diagnostics import LOCAL_FAILURE_STAGES, EvaluatorPreparationDiagnostic
from famou.http_transport import normalize_transport_observation
from famou.models import RunStatus
from famou.source_constraints import MAX_SOURCE_CHECK_BYTES, parse_source_check_evidence
from famou.store import Store

_OUTPUT = "output/result.json"
_MAX_BYTES = 256 * 1024


class ReadOnlyStore(Store):
    @contextmanager
    def _connect(self):
        # Read-only SQLite can rebuild retained SHM after a killed writer. Preserve
        # original evidence and committed WAL rows by opening only a private copy.
        with tempfile.TemporaryDirectory(prefix="lunar129-store-") as directory:
            copied = Path(directory) / "state.db"
            copied.write_bytes(read_regular_file(self.database, 32 * 1024 * 1024))
            wal = self.database.with_name(self.database.name + "-wal")
            if wal.exists() or wal.is_symlink():
                copied.with_name("state.db-wal").write_bytes(read_regular_file(wal, 32 * 1024 * 1024))
            connection = sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA query_only = ON")
                yield connection
            finally:
                connection.close()


def read_json(path, maximum=2 * 1024 * 1024):
    return strict_json(read_regular_file(path, maximum), maximum=maximum)


def read_rows(path):
    if not path.exists():
        return []
    return [strict_json(line, maximum=1024 * 1024)
            for line in read_regular_file(path, 1024 * 1024).splitlines()]


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid_numeric_evidence")
    return value


def quality(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError("invalid_quality_evidence")
    return value


def digest(value, length=64):
    if type(value) is not str or re.fullmatch(f"[a-f0-9]{{{length}}}", value) is None:
        raise ValueError("invalid_digest_evidence")
    return value


def fixed(value, allowed):
    if type(value) is not str or value not in allowed:
        raise ValueError("invalid_fixed_evidence")
    return value


def request_stage(index):
    return {1: "contract_compiler", 2: "evaluator_compiler", 3: "evaluator_auditor"}.get(index, "candidate")


def usage_summary(path):
    starts, ends, public = {}, {}, []
    known = {key: 0 for key in ("input_tokens", "output_tokens", "total_tokens")}
    outcomes = {"succeeded", "provider_error", "invalid_turn", "response_model_mismatch",
                "usage_unavailable", "attempt_deadline_reached", "observed_token_threshold_reached"}
    for row in read_rows(path):
        if type(row) is not dict:
            raise ValueError("invalid_request_row")
        index = row.get("index")
        if type(index) is not int or not 1 <= index <= 20:
            raise ValueError("invalid_request_index")
        if row.get("kind") == "request_started":
            if index != len(starts) + 1 or index in starts or set(starts) != set(ends):
                raise ValueError("invalid_request_order")
            if row.get("requested_model") != "glm-5.2":
                raise ValueError("invalid_requested_model")
            digest(row.get("request_sha256"))
            timeout = number(row.get("request_timeout_seconds"))
            if timeout <= 0 or timeout > 600:
                raise ValueError("invalid_request_timeout")
            starts[index] = row
        elif row.get("kind") == "request_finished":
            if index not in starts or index in ends or row.get("outcome") not in outcomes:
                raise ValueError("invalid_request_finish")
            usage = row.get("usage")
            if usage is not None:
                if (type(usage) is not dict or set(usage) != set(known)
                        or any(type(v) is not int or v < 0 for v in usage.values())
                        or usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]):
                    raise ValueError("invalid_usage_evidence")
                for key, value in usage.items():
                    known[key] += value
            if row.get("known_usage") != known:
                raise ValueError("cumulative_usage_disagreement")
            ends[index] = row
            from famou.runtime import MODEL_FAILURE_REASONS
            reason, status = row.get("failure_reason"), row.get("response_status")
            if reason is not None and reason not in MODEL_FAILURE_REASONS:
                raise ValueError("invalid_failure_evidence")
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                raise ValueError("invalid_status_evidence")
            public.append({"index": index, "stage": request_stage(index), "outcome": row["outcome"],
                           "elapsed_seconds": number(row["elapsed_seconds"]), "failure_reason": reason,
                           "response_status": status, "usage": usage,
                           "request_timeout_seconds": starts[index]["request_timeout_seconds"],
                           "request_sha256": starts[index]["request_sha256"]})
        else:
            raise ValueError("invalid_request_kind")
    complete = path.exists() and set(starts) == set(ends) and all(r.get("usage") is not None for r in ends.values())
    return {"provider_requests": len(starts), "finished_requests": len(ends), "known_usage": known,
            "usage_complete": complete, "total_usage": dict(known) if complete else None,
            "cost_micros": None, "pending_requests": sorted(set(starts) - set(ends)), "requests": public}


def transport_summary(path, requests):
    result, seen = [], set()
    for row in read_rows(path):
        index = row.get("request_index")
        if type(index) is not int or index not in {r["index"] for r in requests} or index in seen:
            raise ValueError("invalid_transport_index")
        seen.add(index)
        detail = row.get("transport_observation")
        if detail is not None:
            detail = normalize_transport_observation(detail)
        request = next(r for r in requests if r["index"] == index)
        if row.get("request_sha256") is not None and row["request_sha256"] != request["request_sha256"]:
            raise ValueError("transport_request_digest_mismatch")
        if row.get("stage") != request["stage"] or row.get("outcome") not in {"response", "failure", "unavailable"}:
            raise ValueError("transport_stage_or_outcome_invalid")
        projected = {"index": index, "stage": row["stage"], "outcome": row["outcome"],
                     "transport_observation": detail}
        for key in ("elapsed_ms", "request_body_bytes", "response_body_bytes"):
            value = row.get(key)
            projected[key] = number(value) if value is not None else None
        result.append(projected)
    return result


def _parent_contract(store, workspace):
    parent = store.get_run_by_workspace(workspace)
    if parent is None:
        raise ValueError("parent_missing")
    plan = store.get_current_plan(parent.id)
    if plan is None or plan.algorithm_problem is None:
        raise ValueError("compiled_contract_missing")
    contract = AlgorithmProblemContract.from_dict(plan.algorithm_problem)
    validate_generated_contract(contract)
    return parent, contract


def verified_preparation(slot):
    """Verify native automatic preparation and the exact registered input without execution."""
    slot = Path(slot).absolute()
    workspace = slot / "workspace"
    store = ReadOnlyStore(slot / "home/state.db")
    held = DirectoryChain(workspace, "measurement_workspace_invalid")
    try:
        parent, contract = _parent_contract(store, workspace)
        if read_regular_file(workspace / "data/raw/limit.json", _MAX_BYTES) != INPUT_BYTES:
            raise ValueError("registered_input_changed")
        validate_automatic_solve_bundle(store, parent.id)
        prepared = automatic_bundle_preparation_status(store, parent.id)
        if prepared is None or prepared.get("status") != "prepared":
            raise ValueError("automatic_preparation_missing")
        bundle = load_evaluator_bundle(workspace / "evaluator-bundle", contract, invocation="snapshot", timeout=5)
        held.check()
        return contract, bundle
    finally:
        held.close()


def _preparation_status(store, parent):
    raw = automatic_bundle_preparation_status(store, parent.id)
    if raw is None:
        return None
    result = {key: raw[key] for key in ("status", "stage", "error_category", "recoverable")}
    fixed(result["status"], {"unknown", "started", "failed", "prepared"})
    fixed(result["stage"], {"preparation", "capability_check", "evaluator_compile", "evaluator_audit",
                            "profile_publish"} | LOCAL_FAILURE_STAGES)
    if result["error_category"] is not None:
        fixed(result["error_category"], {"runtime_error", "validation_error", "cancelled",
                                         "interrupted", "unsupported_verification"})
    if type(result["recoverable"]) is not bool:
        raise ValueError("invalid_preparation_status")
    if raw.get("local_failure") is not None:
        result["local_failure"] = EvaluatorPreparationDiagnostic.from_dict(raw["local_failure"]).to_dict()
    return result


def _delivery(store, parent, contract, cli, workspace):
    if cli.get("run_id") != parent.id:
        raise ValueError("cli_parent_disagreement")
    evolution = cli.get("evolution")
    terminal = evolution.get("materialization") if type(evolution) is dict else None
    if type(terminal) is not dict or terminal.get("mode") != "bundle" or terminal.get("status") != "succeeded":
        raise ValueError("successful_delivery_missing")
    events = [event.get("payload") for event in store.list_events(parent.id)
              if event.get("type") == "bundle_candidate_delivered"]
    if len(events) != 1 or canonical_json(events[0]) != canonical_json(terminal):
        raise ValueError("delivery_event_disagreement")
    child_id = terminal.get("evolution_run_id")
    child = store.get_run(child_id) if type(child_id) is str else None
    if (child is None or child.status != RunStatus.SUCCEEDED or evolution.get("run_id") != child_id
            or Path(child.workspace) != workspace / "evolution-run"
            or terminal.get("parent_run_id") != parent.id
            or terminal.get("contract_sha256") != contract.digest()):
        raise ValueError("delivery_binding_disagreement")
    relative = terminal.get("delivery_path")
    if (type(relative) is not str or Path(relative).is_absolute() or len(Path(relative).parts) != 2
            or Path(relative).parts[0] != ".bundle-deliveries"
            or not Path(relative).name.startswith(".bundle-delivery-")):
        raise ValueError("delivery_path_invalid")
    copied = inspect_bundle_delivery(workspace / relative, expected_delivery_sha256=terminal.get("delivery_sha256"))
    manifest = copied.to_dict()
    if any(terminal.get(key) != value for key, value in manifest["identity"].items()):
        raise ValueError("delivery_identity_disagreement")
    if read_regular_file(copied.delivery_path / "inputs/limit.json", _MAX_BYTES) != INPUT_BYTES:
        raise ValueError("delivery_input_disagreement")
    if (read_regular_file(copied.delivery_path / "evaluation/evaluator.py", 512 * 1024)
            != read_regular_file(workspace / "evaluator-bundle/evaluator.py", 512 * 1024)):
        raise ValueError("delivery_evaluator_disagreement")
    delivered_spec = parse_candidate_evaluation_spec(
        read_regular_file(copied.delivery_path / "evaluation/spec.json", _MAX_BYTES),
    )
    native_profile = read_json(workspace / "bundle-profile.json", 128 * 1024)
    if canonical_json(delivered_spec.to_dict()) != canonical_json(native_profile["evaluator"]):
        raise ValueError("delivery_evaluator_spec_disagreement")
    content = read_regular_file(workspace / _OUTPUT, _MAX_BYTES)
    if read_regular_file(copied.delivery_path / _OUTPUT, _MAX_BYTES) != content:
        raise ValueError("final_output_disagreement")
    rows = [row for row in store.list_artifacts(parent.id)
            if row.get("kind") == "output" and row.get("path") == _OUTPUT]
    if (len(rows) != 1 or rows[0].get("size") != len(content)
            or rows[0].get("sha256") != hashlib.sha256(content).hexdigest()):
        raise ValueError("output_artifact_disagreement")
    if manifest["protocol"] != "lunar-bundle-delivery-source-v1":
        raise ValueError("source_delivery_required")
    evidence = parse_source_check_evidence(
        read_regular_file(copied.delivery_path / "evaluation/source-checks.json", MAX_SOURCE_CHECK_BYTES),
        contract, bundle_sha256=manifest["identity"]["bundle_sha256"],
    )
    if evidence["validity"] is not True:
        raise ValueError("source_check_failed")
    return {"source_evidence_verified": True, "source_check_validity": True,
            "source_python_count": sum(item["path"].endswith(".py") for item in evidence["bundle"]["files"]),
            "source_checks": evidence["checks"], "source_check_protocol": evidence["protocol"],
            "source_delivery_protocol": manifest["protocol"]}


def inspect_product(slot):
    """Failed or absent native evidence receives no official feasibility or quality credit."""
    slot = Path(slot).absolute()
    workspace = slot / "workspace"
    result = {"product_status": None, "product_success": False, "preparation": None,
              "preparation_verified": False, "contract_verified": False, "delivery_verified": False,
              "source_evidence_verified": False, "source_check_validity": None, "source_python_count": 0,
              "source_checks": [], "source_check_protocol": None, "source_delivery_protocol": None,
              "output_check": independent_output(b""), "primary_valid_completion": False,
              "optimum": 3, "quality": None, "quality_gap": None, "optimal": False, "errors": []}
    try:
        result["output_check"] = independent_output(read_regular_file(workspace / _OUTPUT, _MAX_BYTES))
    except Exception:  # noqa: BLE001 - a missing output is measured failure, never execution.
        result["errors"].append("output_unavailable")
    try:
        cli = read_json(slot / "cli.json", 4 * 1024 * 1024)
        if type(cli) is not dict:
            raise ValueError("invalid_cli")
        result["product_status"] = fixed(cli.get("status"), {item.value for item in RunStatus})
    except Exception:  # noqa: BLE001 - keep generated CLI prose private.
        cli = None
        result["errors"].append("cli_unavailable")
    try:
        store = ReadOnlyStore(slot / "home/state.db")
        held = DirectoryChain(workspace, "measurement_workspace_invalid")
        try:
            parent = store.get_run_by_workspace(workspace)
            if parent is None:
                raise ValueError("parent_missing")
            result["preparation"] = _preparation_status(store, parent)
            result["product_success"] = bool(
                cli is not None and cli.get("status") == "succeeded"
                and type(cli.get("evolution")) is dict and cli["evolution"].get("status") == "succeeded"
                and parent.status == RunStatus.SUCCEEDED
            )
            _, contract = _parent_contract(store, workspace)
            result["contract_verified"] = True
            try:
                verified_preparation(slot)
                result["preparation_verified"] = True
            except Exception:  # noqa: BLE001 - retain status even when automatic preparation is invalid.
                result["errors"].append("preparation_unverified")
            if result["product_success"]:
                try:
                    result.update(_delivery(store, parent, contract, cli, workspace))
                    result["delivery_verified"] = True
                except Exception:  # noqa: BLE001 - integrity failures consume the same attempt.
                    result["errors"].append("delivery_unverified")
            held.check()
        finally:
            held.close()
    except Exception:  # noqa: BLE001 - incomplete product runs still produce bounded evidence.
        result["errors"].append("run_evidence_unavailable")
        result.update(preparation_verified=False, delivery_verified=False, source_evidence_verified=False)
    result["primary_valid_completion"] = bool(
        result["product_success"] and result["preparation_verified"] and result["contract_verified"]
        and result["delivery_verified"] and result["source_evidence_verified"]
        and result["source_python_count"] >= 2 and result["output_check"]["validity"]
    )
    if result["primary_valid_completion"]:
        result.update(quality=result["output_check"]["quality"],
                      quality_gap=3 - result["output_check"]["quality"],
                      optimal=result["output_check"]["quality"] == 3)
    return result


def frozen_snapshot(slot, manifest):
    path = slot / "frozen.json"
    if not path.exists():
        return None
    _, bundle = verified_preparation(slot)
    expected = {"fingerprint": bundle.fingerprint, "contract_sha256": bundle.contract_sha256,
                "input_profile_sha256": bundle.input_profile_sha256,
                "files": {p.name: sha(p) for p in sorted(bundle.root.iterdir())}}
    if read_json(path) != expected:
        raise ValueError("frozen_evaluator_changed")
    return expected


def holdout_summary(slot, frozen):
    rows, definitions = [], holdouts()
    paths = sorted((slot / "holdouts").glob("*.json"))
    if (paths and frozen is None) or len(paths) > len(definitions):
        raise ValueError("holdouts_without_frozen_evaluator")
    for index, path in enumerate(paths, 1):
        if path.name != f"{index:03d}.json":
            raise ValueError("holdout_order_changed")
        row, definition = read_json(path), definitions[index - 1]
        if (row.get("name") != definition["name"] or type(row.get("matched")) is not bool
                or type(row.get("snapshot_started")) is not bool):
            raise ValueError("holdout_identity_changed")
        if row.get("status") not in {"completed", "failed"}:
            raise ValueError("holdout_status_changed")
        observed = row.get("observed")
        if observed is not None:
            expected = definition["expected"]
            if (type(observed) is not dict or set(observed) != {
                    "validity", "quality", "combined_score", "constraint_code_present"}
                    or type(observed["validity"]) is not int or observed["validity"] not in (0, 1)
                    or type(observed["constraint_code_present"]) is not bool):
                raise ValueError("holdout_observation_invalid")
            quality(observed["quality"])
            number(observed["combined_score"])
            matched = (row["status"] == "completed" and observed["validity"] == expected["validity"]
                       and observed["quality"] == expected["quality"]
                       and observed["combined_score"] == expected["combined_score"]
                       and (expected["validity"] == 1 or observed["constraint_code_present"]))
        else:
            if row["status"] == "completed":
                raise ValueError("completed_holdout_missing_observation")
            matched = False
        if observed is not None and not row["snapshot_started"]:
            raise ValueError("unstarted_holdout_has_observation")
        if row["matched"] != matched:
            raise ValueError("holdout_match_disagreement")
        rows.append({"name": definition["name"], "status": row["status"], "matched": matched,
                     "observed": observed, "snapshot_started": row["snapshot_started"]})
    return {"planned": 8, "recorded": len(rows), "executed": sum(r["snapshot_started"] for r in rows),
            "execution_count_scope": "retained_snapshot_started_rows",
            "matched": sum(r["matched"] for r in rows), "rows": rows}


def local_failure_summary(product, usage, frozen):
    preparation = product.get("preparation")
    if preparation is None or preparation.get("local_failure") is None:
        return None
    detail = EvaluatorPreparationDiagnostic.from_dict(preparation["local_failure"]).to_dict()
    if (preparation.get("status") != "failed" or preparation.get("stage") != detail["stage"]
            or preparation.get("error_category") != "validation_error"
            or preparation.get("recoverable") is not False or frozen is not None
            or product.get("preparation_verified")):
        raise ValueError("local_failure_context_disagreement")
    expected = 2 if detail["stage"].startswith("compiler_") else 3
    requests = usage["requests"]
    if (usage["provider_requests"] != expected or usage["finished_requests"] != expected
            or usage["pending_requests"] or len(requests) != expected
            or any(row["index"] != index or row["outcome"] != "succeeded"
                   or row["stage"] != request_stage(index) for index, row in enumerate(requests, 1))):
        raise ValueError("local_failure_request_disagreement")
    return detail


def summarize(manifest):
    root = REPO / manifest["campaign_root"]
    slot = root / "attempt-001"
    start, finish = read_json(root / "started.json"), read_json(root / "finished.json")
    for marker in (start, finish, read_json(slot / "started.json")):
        if marker.get("campaign_id") != CAMPAIGN_ID or marker.get("manifest_sha256") != sha(MANIFEST):
            raise ValueError("registration_binding_changed")
    process = read_json(slot / "finished.json")
    process_status = fixed(process.get("process_status"), {"exited", "timed_out", "interrupted", "supervisor_failed"})
    exit_code = process.get("exit_code")
    if exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255):
        raise ValueError("invalid_exit_code")
    cleanup = process.get("cleanup_verified") is True and process.get("remaining_observed_pids") == []
    usage = usage_summary(slot / "calls.jsonl")
    product = inspect_product(slot)
    frozen = frozen_snapshot(slot, manifest)
    holds = holdout_summary(slot, frozen)
    worker = read_json(slot / "worker-finished.json") if (slot / "worker-finished.json").exists() else None
    worker_status = fixed(worker.get("status"), {"failed", "completed"}) if worker else None
    worker_stage = fixed(worker.get("stage"), {"setup", "solve", "preparation_check", "holdouts", "finished"}) if worker else None
    if worker is not None and worker.get("frozen") != frozen:
        raise ValueError("worker_freeze_disagreement")
    if worker is not None and worker.get("holdouts") != [
            read_json(path) for path in sorted((slot / "holdouts").glob("*.json"))]:
        raise ValueError("worker_holdouts_disagreement")
    if worker_status == "completed" and (frozen is None or holds["recorded"] != 8):
        raise ValueError("completed_worker_missing_holdouts")
    if frozen is not None and (usage["finished_requests"] < 3 or any(
            row["outcome"] != "succeeded" for row in usage["requests"][:3])):
        raise ValueError("freeze_without_three_accepted_requests")
    local_failure = local_failure_summary(product, usage, frozen)
    primary = bool(product["primary_valid_completion"] and frozen is not None)
    completed = worker_status == "completed" and process_status == "exited" and exit_code == 0 and cleanup
    official_quality = primary and completed
    result = {"schema_version": "1", "campaign_id": CAMPAIGN_ID, "manifest_sha256": sha(MANIFEST),
              "registration_commit": digest(start["registration_commit"], 40),
              "product_commit": digest(manifest["product_commit"], 40), "planned_attempts": 1,
              "primary_success": int(primary), "preparation_success": int(frozen is not None),
              "joint_success": int(primary and holds["matched"] == 8 and completed),
              "product": product, "frozen": frozen, "holdouts": holds, "usage": usage,
              "transport": transport_summary(slot / "transport.jsonl", usage["requests"]),
              "cleanup_verified": cleanup, "process_status": process_status, "exit_code": exit_code,
              "elapsed_seconds": number(process["elapsed_seconds"]), "worker_status": worker_status,
              "worker_stage": worker_stage, "local_failure": local_failure, "known_optimum": 3,
              "quality": product["quality"] if official_quality else None,
              "gap": product["quality_gap"] if official_quality else None,
              "optimal": bool(official_quality and product["optimal"])}
    inventory = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinked_retained_evidence")
        if path.is_file():
            raw = read_regular_file(path, 32 * 1024 * 1024)
            inventory[path.relative_to(root).as_posix()] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    target = HERE.parent / "postrun"
    target.mkdir(exist_ok=False)
    write_new(target / "results.json", result)
    write_new(target / "evidence.json", {"schema_version": "1", "files": inventory})
    return result
