"""Read retained acceptance evidence without executing models, candidates or evaluators."""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:  # Package imports for offline tests; script imports for the one-shot worker.
    from .campaign import CampaignError, ClosureCampaign
    from .case import (
        CAMPAIGN_ID,
        INPUT_BYTES,
        holdouts,
        independent_output,
        validate_generated_contract,
    )
    from .runner import HERE, LIMITS, MANIFEST, REPO, sha, write_new
except ImportError:  # pragma: no cover - exercised by the real script entry point
    from campaign import CampaignError, ClosureCampaign
    from case import (
        CAMPAIGN_ID,
        INPUT_BYTES,
        holdouts,
        independent_output,
        validate_generated_contract,
    )
    from runner import HERE, LIMITS, MANIFEST, REPO, sha, write_new

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
from famou.evaluator_request_diagnostics import normalize_evaluator_request_failure
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
        with tempfile.TemporaryDirectory(prefix="lunar139-store-") as directory:
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


def usage_summary(path):
    starts, ends, public = {}, {}, []
    known = {key: 0 for key in ("input_tokens", "output_tokens", "total_tokens")}
    outcomes = {"succeeded", "provider_error", "invalid_turn", "response_model_mismatch",
                "usage_unavailable", "attempt_deadline_reached", "observed_token_threshold_reached"}
    for row in read_rows(path):
        if type(row) is not dict:
            raise ValueError("invalid_request_row")
        index = row.get("index")
        if type(index) is not int or not 1 <= index <= LIMITS["max_requests"]:
            raise ValueError("invalid_request_index")
        if row.get("kind") == "request_started":
            if index != len(starts) + 1 or index in starts or set(starts) != set(ends):
                raise ValueError("invalid_request_order")
            if ends and (ends[index - 1]["outcome"] != "succeeded"
                         or known["total_tokens"] >= LIMITS["token_stop_threshold"]):
                raise ValueError("request_after_admission_stopped")
            if row.get("requested_model") != "glm-5.2":
                raise ValueError("invalid_requested_model")
            digest(row.get("request_sha256"))
            timeout = number(row.get("request_timeout_seconds"))
            if timeout <= 0 or timeout > LIMITS["preparation_request_seconds"]:
                raise ValueError("invalid_request_timeout")
            starts[index] = row
        elif row.get("kind") == "request_finished":
            if index not in starts or index in ends or row.get("outcome") not in outcomes:
                raise ValueError("invalid_request_finish")
            usage = row.get("usage")
            if usage is not None:
                if (type(usage) is not dict or set(usage) != set(known)
                        or any(type(v) is not int or not 0 <= v <= 10**12 for v in usage.values())
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
            observation = row.get("observation")
            if observation is not None:
                observation = normalize_evaluator_request_failure({
                    "schema_version": "1", "reason": reason, "response_status": status,
                    "request_observation": observation, "transport_observation": None,
                })["request_observation"]
            public.append({"index": index, "stage": None, "outcome": row["outcome"],
                           "elapsed_seconds": number(row["elapsed_seconds"]), "failure_reason": reason,
                           "started_elapsed_seconds": (number(starts[index]["elapsed_seconds"])
                                                       if "elapsed_seconds" in starts[index] else None),
                           "response_status": status, "request_observation": observation, "usage": usage,
                           "request_timeout_seconds": starts[index]["request_timeout_seconds"],
                           "request_sha256": starts[index]["request_sha256"]})
        else:
            raise ValueError("invalid_request_kind")
    complete = path.exists() and set(starts) == set(ends) and all(r.get("usage") is not None for r in ends.values())
    return {"provider_requests": len(starts), "finished_requests": len(ends), "known_usage": known,
            "usage_complete": complete, "total_usage": dict(known) if complete else None,
            "cost_micros": None, "pending_requests": sorted(set(starts) - set(ends)), "requests": public}


def transport_summary(path, requests):
    # Keep the public array aligned with the accepted request ledger.  A missing
    # optional sidecar row is an unknown transport observation, never evidence
    # of a successful exchange.
    result, seen = {}, set()
    request_by_index = {request["index"]: request for request in requests}
    for row in read_rows(path):
        if type(row) is not dict:
            raise ValueError("invalid_transport_row")
        index = row.get("request_index")
        if type(index) is not int or index not in request_by_index or index in seen:
            raise ValueError("invalid_transport_index")
        seen.add(index)
        detail = row.get("transport_observation")
        if detail is not None:
            detail = normalize_transport_observation(detail)
        request = request_by_index[index]
        exchanges = row.get("exchange_count")
        if type(exchanges) is not int or not 0 <= exchanges <= LIMITS["max_requests"]:
            raise ValueError("invalid_transport_exchange_count")
        if exchanges == 1 and row.get("request_sha256") != request["request_sha256"]:
            raise ValueError("transport_request_digest_mismatch")
        if row.get("outcome") not in {"response", "failure", "unavailable"}:
            raise ValueError("transport_stage_or_outcome_invalid")
        status = row.get("status")
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            raise ValueError("invalid_transport_status")
        if exchanges != 1 and (status is not None or detail is not None or row.get("request_sha256") is not None
                               or row["outcome"] != "unavailable"):
            raise ValueError("transport_exchange_binding_missing")
        if (status is not None and request["response_status"] is not None
                and status != request["response_status"]):
            raise ValueError("transport_ledger_status_disagreement")
        context_bound = row.get("context_bound") is True
        stage = row.get("stage")
        if stage not in {
            "contract_compiler", "evaluator_compiler", "evaluator_auditor",
            "candidate_generation", "unbound",
        }:
            raise ValueError("transport_stage_or_outcome_invalid")
        identity = {
            key: row.get(key) for key in ("run_id", "task_id", "budget_id", "max_tool_steps")
        }
        if stage == "candidate_generation":
            if (not context_bound or any(type(identity[key]) is not str or not identity[key]
                                         or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", identity[key]) is None
                                         for key in ("run_id", "task_id", "budget_id"))
                    or type(identity["max_tool_steps"]) is not int
                    or identity["max_tool_steps"] != LIMITS["candidate_generation_max_steps"]):
                raise ValueError("candidate_request_context_invalid")
        elif stage == "unbound":
            if context_bound or any(value is not None for value in identity.values()):
                raise ValueError("unbound_request_context_invalid")
        elif not context_bound or any(value is not None for value in identity.values()):
            raise ValueError("preparation_request_context_invalid")
        projected = {"index": index, "stage": stage, "outcome": row["outcome"],
                     "context_bound": context_bound, **identity,
                     "transport_observation": detail, "status": status, "exchange_count": exchanges}
        for key in ("elapsed_ms", "request_body_bytes", "response_body_bytes"):
            value = row.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= 10**12):
                raise ValueError("invalid_transport_counter")
            projected[key] = value
        result[index] = projected
        request.update({"stage": stage, **identity})

    # Diagnostics are optional, so an absent row remains a bounded, explicit
    # unknown.  This also prevents callers from treating a shorter array as a
    # successful prefix of the request ledger.
    for request in requests:
        index = request["index"]
        if index not in result:
            result[index] = {
                "index": index,
                "stage": request["stage"],
                "outcome": "unavailable",
                "context_bound": False,
                "run_id": None,
                "task_id": None,
                "budget_id": None,
                "max_tool_steps": None,
                "transport_observation": None,
                "status": None,
                "exchange_count": 0,
                "elapsed_ms": None,
                "request_body_bytes": None,
                "response_body_bytes": None,
            }
    return [result[request["index"]] for request in requests]


def _request_stage(requests, index):
    if not 1 <= index <= len(requests):
        raise ValueError("request_stage_missing")
    stage = requests[index - 1].get("stage")
    if stage not in {
        "contract_compiler", "evaluator_compiler", "evaluator_auditor",
        "candidate_generation", "unbound",
    }:
        raise ValueError("request_stage_missing")
    return stage


def _preparation_request_stage(requests, index):
    expected = ("contract_compiler", "evaluator_compiler", "evaluator_auditor")
    if not 1 <= index <= len(expected) or _request_stage(requests, index) != expected[index - 1]:
        raise ValueError("preparation_request_stage_disagreement")
    return expected[index - 1]


def budget_summary(worker, process, usage, transport):
    """Bind the terminal guard to its ledger; incomplete evidence gets no success credit."""
    guard = worker.get("guard") if worker is not None else None
    result = {"verified": False, "stopped_reason": None, "ledger_complete": False}
    if guard is None:
        return result
    if type(guard) is not dict or not {
        "provider_requests", "finished_requests", "known_usage", "usage_complete",
        "stopped_reason", "elapsed_seconds",
    } <= set(guard):
        raise ValueError("invalid_guard_evidence")
    for key in ("provider_requests", "finished_requests"):
        if type(guard.get(key)) is not int or guard[key] != usage[key]:
            raise ValueError("guard_ledger_disagreement")
    if (type(guard.get("usage_complete")) is not bool
            or guard["usage_complete"] != usage["usage_complete"]
            or type(guard.get("known_usage")) is not dict
            or any(type(value) is not int for value in guard["known_usage"].values())
            or guard["known_usage"] != usage["known_usage"]):
        raise ValueError("guard_usage_disagreement")
    stopped = guard.get("stopped_reason")
    if stopped is not None:
        fixed(stopped, {
            "runtime_registration_mismatch", "request_limit_reached", "observed_token_threshold_reached",
            "attempt_deadline_reached", "request_timeout_invalid", "request_journal_unavailable",
            "provider_error", "invalid_turn", "response_model_mismatch", "usage_unavailable",
        })
    result["stopped_reason"] = stopped
    requests = usage["requests"]
    complete = bool(
        usage["provider_requests"] >= 4 and usage["provider_requests"] == usage["finished_requests"]
        and not usage["pending_requests"] and len(requests) == usage["provider_requests"]
    )
    result["ledger_complete"] = complete
    guard_elapsed = number(guard.get("elapsed_seconds"))
    worker_elapsed = number(worker.get("elapsed_seconds"))
    process_elapsed = number(process.get("elapsed_seconds"))
    bound = bool(
        complete and [row["stage"] for row in requests[:3]]
        == ["contract_compiler", "evaluator_compiler", "evaluator_auditor"]
        and all(row["stage"] == "candidate_generation" for row in requests[3:])
        and all(row["context_bound"] for row in transport)
        and all(row["outcome"] == "succeeded" for row in requests)
    )
    previous_end = 0.0
    time_verified = bound
    for index, row in enumerate(requests):
        started = row["started_elapsed_seconds"]
        ceiling = (LIMITS["preparation_request_seconds"]
                   if row["stage"] in {"evaluator_compiler", "evaluator_auditor"}
                   else LIMITS["request_seconds"])
        if row["request_timeout_seconds"] > ceiling:
            raise ValueError("request_stage_timeout_disagreement")
        if started is None:
            time_verified = False
            continue
        end = started + row["elapsed_seconds"]
        if started < previous_end:
            raise ValueError("request_clock_order_disagreement")
        previous_end = end
        if (end > guard_elapsed or end >= LIMITS["wall_seconds"]
                or row["elapsed_seconds"] > row["request_timeout_seconds"]):
            time_verified = False
        if index < 3 and end >= LIMITS["preparation_wall_seconds"]:
            time_verified = False
    result["verified"] = bool(
        bound and time_verified and stopped is None
        and usage["known_usage"]["total_tokens"] < LIMITS["token_stop_threshold"]
        and max(guard_elapsed, worker_elapsed, process_elapsed) < LIMITS["wall_seconds"]
    )
    return result


def preparation_policy(store, parent, *, require_start=False):
    """Only this newly registered explicit policy can establish preparation success."""
    events = store.list_events(parent.id)
    rows = [row.get("payload") for row in events if row.get("type") == "evolution_requested"]
    if len(rows) != 1 or type(rows[0]) is not dict or rows[0].get("bundle_mode") != "compiled":
        raise ValueError("preparation_policy_missing")
    policy, result = rows[0], {}
    definitions = (("timeout", "candidate_timeout", "candidate_seconds"),
                   ("evaluator_preparation_timeout", "evaluator_preparation_timeout", "preparation_request_seconds"),
                   ("evaluator_preparation_wall_timeout", "evaluator_preparation_wall_timeout", "preparation_wall_seconds"))
    for field, public, limit in definitions:
        value = policy.get(field)
        if (type(value) not in {int, float} or value != LIMITS[limit]
                or policy.get(field + "_source") != "explicit"):
            raise ValueError("registered_preparation_policy_disagreement")
        result[public] = {"seconds": value, "source": "explicit"}
    if require_start:
        starts = [row.get("payload") for row in events if row.get("type") == "bundle_preparation_started"]
        if len(starts) != 1 or type(starts[0]) is not dict:
            raise ValueError("preparation_start_missing")
        start = starts[0]
        attempt = start.get("attempt_id")
        if type(attempt) is not str or re.fullmatch(r"preparation-[a-f0-9]{32}", attempt) is None:
            raise ValueError("preparation_start_invalid")
        expected = {"schema_version": "2", "parent_run_id": parent.id, "attempt_id": attempt,
                    "status": "started", "stage": "preparation", "error_category": None, "recoverable": False,
                    "preparation_budgets": {"candidate_timeout_seconds": LIMITS["candidate_seconds"],
                                            "request_timeout_seconds": LIMITS["preparation_request_seconds"],
                                            "wall_timeout_seconds": LIMITS["preparation_wall_seconds"]}}
        budgets = start.get("preparation_budgets")
        if (type(budgets) is not dict or set(budgets) != set(expected["preparation_budgets"])
                or any(type(value) not in {int, float} for value in budgets.values())
                or type(start.get("recoverable")) is not bool or start != expected):
            raise ValueError("preparation_start_policy_disagreement")
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
        preparation_policy(store, parent, require_start=True)
        if read_regular_file(workspace / "data/raw/limit.json", _MAX_BYTES) != INPUT_BYTES:
            raise ValueError("registered_input_changed")
        validate_automatic_solve_bundle(store, parent.id)
        prepared = automatic_bundle_preparation_status(store, parent.id)
        if prepared is None or prepared.get("status") != "prepared":
            raise ValueError("automatic_preparation_missing")
        profile = read_json(workspace / "bundle-profile.json", 128 * 1024)
        for part in (profile, profile.get("evaluator")):
            if (type(part) is not dict or type(part.get("timeout_seconds")) not in {int, float}
                    or part["timeout_seconds"] != LIMITS["candidate_seconds"]
                    or any("preparation" in key for key in part)):
                raise ValueError("profile_candidate_timeout_disagreement")
        bundle = load_evaluator_bundle(workspace / "evaluator-bundle", contract, invocation="snapshot", timeout=5)
        held.check()
        return contract, bundle
    finally:
        held.close()


def _preparation_status(store, parent):
    raw = automatic_bundle_preparation_status(store, parent.id)
    if raw is None:
        return None
    result = {key: raw[key] for key in ("schema_version", "status", "stage", "error_category", "recoverable")}
    fixed(result["schema_version"], {"1", "2", "3", "4"})
    fixed(result["status"], {"unknown", "started", "failed", "prepared"})
    fixed(result["stage"], {"preparation", "capability_check", "evaluator_compile", "evaluator_audit",
                            "profile_publish"} | LOCAL_FAILURE_STAGES)
    if result["error_category"] is not None:
        fixed(result["error_category"], {"runtime_error", "validation_error", "cancelled",
                                         "interrupted", "unsupported_verification", "preparation_timeout"})
    if type(result["recoverable"]) is not bool:
        raise ValueError("invalid_preparation_status")
    if raw.get("local_failure") is not None:
        result["local_failure"] = EvaluatorPreparationDiagnostic.from_dict(raw["local_failure"]).to_dict()
    if raw.get("request_failure") is not None:
        result["request_failure"] = normalize_evaluator_request_failure(raw["request_failure"])
    if raw.get("wall_failure") is not None:
        detail = raw["wall_failure"]
        if (type(detail) is not dict or set(detail) != {"schema_version", "reason", "elapsed_ms", "wall_timeout_ms"}
                or detail.get("schema_version") != "1" or detail.get("reason") != "wall_timeout"
                or type(detail.get("wall_timeout_ms")) is not int
                or detail["wall_timeout_ms"] != LIMITS["preparation_wall_seconds"] * 1000
                or type(detail.get("elapsed_ms")) is not int
                or not detail["wall_timeout_ms"] <= detail["elapsed_ms"] <= 86400000):
            raise ValueError("invalid_preparation_wall_failure")
        result["wall_failure"] = dict(detail)
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
    from .retained_chain import verify_retained_chain

    result = {"product_status": None, "persisted_parent_status": None, "product_success": False,
              "closure_verified": False, "completed_candidates": 0, "closure_sha256": None,
              "stage_receipts": [], "native_candidates": [], "selected_candidate_id": None,
              "preparation": None, "preparation_budgets": None,
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
            result["persisted_parent_status"] = fixed(parent.status.value, {item.value for item in RunStatus})
            result["preparation"] = _preparation_status(store, parent)
            try:
                result["preparation_budgets"] = preparation_policy(store, parent)
            except ValueError:
                result["errors"].append("preparation_policy_unverified")
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
                if result["delivery_verified"]:
                    try:
                        result.update(verify_retained_chain(slot, store, parent, contract, cli))
                    except Exception:  # noqa: BLE001 - missing generation never follows from delivery.
                        result["errors"].append("closure_unverified")
            held.check()
        finally:
            held.close()
    except Exception:  # noqa: BLE001 - incomplete product runs still produce bounded evidence.
        result["errors"].append("run_evidence_unavailable")
        result.update(preparation_verified=False, delivery_verified=False, source_evidence_verified=False,
                      closure_verified=False, completed_candidates=0)
    result["primary_valid_completion"] = bool(
        result["product_success"] and result["preparation_verified"] and result["contract_verified"]
        and result["delivery_verified"] and result["source_evidence_verified"]
        and result["closure_verified"]
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
                   or row["stage"] != _preparation_request_stage(requests, index)
                   for index, row in enumerate(requests, 1))):
        raise ValueError("local_failure_request_disagreement")
    return detail


def request_failure_summary(product, usage, frozen):
    preparation = product.get("preparation")
    if preparation is None or preparation.get("request_failure") is None:
        return None
    detail = normalize_evaluator_request_failure(preparation["request_failure"])
    if (preparation.get("status") != "failed" or preparation.get("recoverable") is not True
            or preparation.get("error_category") not in {"runtime_error", "preparation_timeout"}
            or product.get("persisted_parent_status") != "running" or frozen is not None
            or product.get("preparation_verified")):
        raise ValueError("request_failure_context_disagreement")
    expected = {"evaluator_compile": 2, "evaluator_audit": 3}.get(preparation.get("stage"))
    requests = usage["requests"]
    if (expected is None or usage["provider_requests"] != expected or usage["finished_requests"] != expected
            or usage["pending_requests"] or len(requests) != expected
            or any(row["index"] != index or row["stage"] != _preparation_request_stage(requests, index)
                   or row["outcome"] != "succeeded" for index, row in enumerate(requests[:-1], 1))):
        raise ValueError("request_failure_request_disagreement")
    failed = requests[-1]
    if (failed["index"] != expected or failed["stage"] != _preparation_request_stage(requests, expected)
            or failed["outcome"] != "provider_error" or failed["failure_reason"] != detail["reason"]
            or failed["response_status"] != detail["response_status"]
            or failed["request_observation"] != detail["request_observation"]):
        raise ValueError("request_failure_ledger_disagreement")
    observation = detail["request_observation"]
    if (observation is not None and observation["request_timeout_ms"] is not None
            and observation["request_timeout_ms"] != math.floor(failed["request_timeout_seconds"] * 1000)):
        raise ValueError("request_failure_timeout_disagreement")
    return detail


def wall_failure_summary(product, usage, frozen):
    preparation = product.get("preparation")
    if preparation is None or preparation.get("wall_failure") is None:
        return None
    if (preparation.get("schema_version") != "4" or preparation.get("status") != "failed"
            or preparation.get("error_category") != "preparation_timeout" or preparation.get("recoverable") is not True
            or product.get("persisted_parent_status") != "running" or frozen is not None
            or product.get("preparation_verified") or usage["provider_requests"] > 3
            or usage["pending_requests"]):
        raise ValueError("wall_failure_context_disagreement")
    if any(row["outcome"] != "succeeded" for row in usage["requests"][:-1]):
        raise ValueError("wall_failure_request_disagreement")
    return dict(preparation["wall_failure"])


def summarize(manifest):
    root = REPO / manifest["campaign_root"]
    slot = root / "attempt-001"
    start, finish = read_json(root / "started.json"), read_json(root / "finished.json")
    for marker in (start, finish, read_json(slot / "started.json")):
        if (type(marker) is not dict or marker.get("campaign_id") != CAMPAIGN_ID
                or marker.get("manifest_sha256") != sha(MANIFEST)
                or marker.get("registration_id") != manifest.get("registration_id")
                or marker.get("attempt_id") != manifest.get("attempt_id")
                or marker.get("registration_commit") != start.get("registration_commit")):
            raise ValueError("registration_binding_changed")
    process = read_json(slot / "finished.json")
    process_status = fixed(process.get("process_status"), {"exited", "timed_out", "interrupted", "supervisor_failed"})
    exit_code = process.get("exit_code")
    if exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255):
        raise ValueError("invalid_exit_code")
    cleanup = process.get("cleanup_verified") is True and process.get("remaining_observed_pids") == []
    usage = usage_summary(slot / "calls.jsonl")
    transport = transport_summary(slot / "transport.jsonl", usage["requests"])
    product = inspect_product(slot)
    frozen = frozen_snapshot(slot, manifest)
    holds = holdout_summary(slot, frozen)
    worker = read_json(slot / "worker-finished.json") if (slot / "worker-finished.json").exists() else None
    worker_status = fixed(worker.get("status"), {"failed", "completed"}) if worker else None
    worker_stage = fixed(worker.get("stage"), {
        "setup", "solve", "preparation_check", "holdout_gate", "holdouts", "finished",
    }) if worker else None
    if worker is not None and worker.get("frozen") != frozen:
        raise ValueError("worker_freeze_disagreement")
    if worker is not None and worker.get("holdouts") != [
            read_json(path) for path in sorted((slot / "holdouts").glob("*.json"))]:
        raise ValueError("worker_holdouts_disagreement")
    if worker_status == "completed" and (frozen is None or holds["recorded"] != 8):
        raise ValueError("completed_worker_missing_holdouts")
    budgets = budget_summary(worker, process, usage, transport)
    local_failure = local_failure_summary(product, usage, frozen)
    request_failure = request_failure_summary(product, usage, frozen)
    wall_failure = wall_failure_summary(product, usage, frozen)
    primary = bool(product["primary_valid_completion"] and product.get("closure_verified") is True
                   and frozen is not None and budgets["verified"])
    native_exit = worker.get("native_exit_code") if worker else None
    if native_exit is not None and (type(native_exit) is not int or not -255 <= native_exit <= 255):
        raise ValueError("invalid_native_exit_code")
    completed = (worker_status == "completed" and worker_stage == "finished" and process_status == "exited"
                 and exit_code == 0 and native_exit == 0 and cleanup)
    official_quality = primary and completed
    result = {"schema_version": "1", "campaign_id": CAMPAIGN_ID, "manifest_sha256": sha(MANIFEST),
              "registration_commit": digest(start["registration_commit"], 40),
              "product_commit": digest(manifest["product_commit"], 40), "planned_attempts": 1,
              "primary_success": int(primary), "preparation_success": int(frozen is not None),
              "joint_success": int(primary and holds["matched"] == 8 and completed),
              "product": product, "frozen": frozen, "holdouts": holds, "usage": usage,
              "transport": transport, "budgets": budgets,
              "cleanup_verified": cleanup, "process_status": process_status, "exit_code": exit_code,
              "native_exit_code": native_exit,
              "elapsed_seconds": number(process["elapsed_seconds"]), "worker_status": worker_status,
              "worker_stage": worker_stage, "local_failure": local_failure,
              "request_failure": request_failure, "wall_failure": wall_failure, "known_optimum": 3,
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


def audit(campaign: ClosureCampaign) -> dict:
    """Audit offline fixture evidence without invoking a provider or source."""
    return campaign.audit()


def public_result(campaign: ClosureCampaign) -> dict:
    """Return the allow-listed projection used by the provider-free contract tests."""
    return campaign.public_result()


def assert_public_safe(result: dict) -> None:
    """Fail closed if private transport or source fields enter a projection."""
    forbidden = ("prompt", "response", "credential", "endpoint", "url", "exception", "source")
    serialized = repr(result).lower()
    if any(token in serialized for token in forbidden):
        raise CampaignError("unsafe_public_projection")
