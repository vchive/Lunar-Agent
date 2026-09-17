"""Read retained diagnostic results without executing model, evaluator or candidate code."""
from __future__ import annotations

import hashlib
import json
import math
import re

from campaign import CAMPAIGN_ID, HERE, MANIFEST, REPO, sha, write_new
from case import contract, holdouts

from famou._benchmark_files import read_regular_file
from famou.evaluator_bundle import load_evaluator_bundle
from famou.evaluator_diagnostics import EvaluatorPreparationDiagnostic
from famou.http_transport import normalize_transport_observation


def read_json(path):
    return json.loads(read_regular_file(path, 2 * 1024 * 1024))


def read_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in read_regular_file(path, 1024 * 1024).splitlines()]


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
    rows = read_rows(path)
    starts, ends = {}, {}
    known = {key: 0 for key in ("input_tokens", "output_tokens", "total_tokens")}
    outcomes = {"succeeded", "provider_error", "invalid_turn", "response_model_mismatch",
                "usage_unavailable", "attempt_deadline_reached", "observed_token_threshold_reached"}
    public = []
    for row in rows:
        index = row.get("index")
        if type(index) is not int or not 1 <= index <= 2:
            raise ValueError("invalid_request_index")
        if row.get("kind") == "request_started":
            if index != len(starts) + 1 or index in starts or (index == 2 and 1 not in ends):
                raise ValueError("invalid_request_order")
            if row.get("requested_model") != "glm-5.2":
                raise ValueError("invalid_requested_model")
            digest(row.get("request_sha256"))
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
            reason = row.get("failure_reason")
            from famou.runtime import MODEL_FAILURE_REASONS
            if reason is not None and reason not in MODEL_FAILURE_REASONS:
                raise ValueError("invalid_failure_evidence")
            status = row.get("response_status")
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                raise ValueError("invalid_status_evidence")
            public.append({"index": index, "stage": "evaluator_compiler" if index == 1 else "evaluator_auditor",
                           "outcome": row["outcome"], "elapsed_seconds": number(row["elapsed_seconds"]),
                           "failure_reason": reason, "response_status": status, "usage": usage,
                           "request_timeout_seconds": number(starts[index]["request_timeout_seconds"]),
                           "request_sha256": starts[index]["request_sha256"]})
        else:
            raise ValueError("invalid_request_kind")
    complete = path.exists() and set(starts) == set(ends) and all(r.get("usage") is not None for r in ends.values())
    return {"provider_requests": len(starts), "finished_requests": len(ends), "known_usage": known,
            "usage_complete": complete, "total_usage": dict(known) if complete else None,
            "cost_micros": None, "pending_requests": sorted(set(starts) - set(ends)), "requests": public}


def transport_summary(path, requests):
    rows = read_rows(path)
    # Validate public projection again; generated/provider prose never crosses this reader.
    result, seen = [], set()
    for row in rows:
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


def frozen_snapshot(slot, manifest):
    path = slot / "frozen.json"
    if not path.exists():
        return None
    recorded = read_json(path)
    bundle = load_evaluator_bundle(slot / "workspace/evaluator-bundle", contract(),
                                   input_profile=manifest["input_profile"], invocation="snapshot",
                                   timeout=manifest["limits"]["request_seconds"])
    expected = {"fingerprint": bundle.fingerprint, "contract_sha256": bundle.contract_sha256,
                "input_profile_sha256": bundle.input_profile_sha256,
                "files": {p.name: sha(p) for p in sorted(bundle.root.iterdir())}}
    if recorded != expected:
        raise ValueError("frozen_evaluator_changed")
    return expected


def holdout_summary(slot, frozen):
    rows = []
    definitions = holdouts()
    paths = sorted((slot / "holdouts").glob("*.json"))
    if paths and frozen is None or len(paths) > len(definitions):
        raise ValueError("holdouts_without_frozen_evaluator")
    for index, path in enumerate(paths, 1):
        if path.name != f"{index:03d}.json":
            raise ValueError("holdout_order_changed")
        row = read_json(path)
        definition = definitions[index - 1]
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
        rows.append({"name": definition["name"], "status": row["status"],
                     "matched": matched, "observed": observed, "snapshot_started": row["snapshot_started"]})
    return {"planned": 8, "recorded": len(rows), "executed": sum(r["snapshot_started"] for r in rows),
            "matched": sum(r["matched"] for r in rows), "rows": rows}


def local_failure_summary(worker, usage, frozen):
    """Validate optional local detail against native stage and accepted request evidence."""
    if worker is None or worker.get("local_failure") is None:
        return None
    try:
        detail = EvaluatorPreparationDiagnostic.from_dict(worker["local_failure"]).to_dict()
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_local_failure_evidence") from exc
    if (worker.get("status") != "failed" or worker.get("stage") != "preparation"
            or worker.get("error_class") != "EvaluatorPreparationError"
            or frozen is not None or worker.get("frozen") is not None):
        raise ValueError("local_failure_context_disagreement")
    expected = 1 if detail["stage"].startswith("compiler_") else 2
    requests = usage["requests"]
    if (usage["provider_requests"] != expected or usage["finished_requests"] != expected
            or usage["pending_requests"] or len(requests) != expected
            or any(row["index"] != index or row["outcome"] != "succeeded"
                   or row["stage"] != ("evaluator_compiler" if index == 1 else "evaluator_auditor")
                   for index, row in enumerate(requests, 1))):
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
    if usage["requests"] and usage["requests"][0]["request_sha256"] != manifest["compiler_request"]["sha256"]:
        raise ValueError("compiler_request_changed")
    frozen = frozen_snapshot(slot, manifest)
    holds = holdout_summary(slot, frozen)
    worker = read_json(slot / "worker-finished.json") if (slot / "worker-finished.json").exists() else None
    worker_status = fixed(worker.get("status"), {"failed", "completed"}) if worker else None
    worker_stage = fixed(worker.get("stage"), {"setup", "preparation", "holdouts", "finished"}) if worker else None
    if worker is not None and worker.get("frozen") != frozen:
        raise ValueError("worker_freeze_disagreement")
    if frozen is not None and (usage["provider_requests"] != 2 or usage["finished_requests"] != 2
                               or any(r["outcome"] != "succeeded" for r in usage["requests"])):
        raise ValueError("freeze_without_two_accepted_requests")
    local_failure = local_failure_summary(worker, usage, frozen)
    result = {"schema_version": "1", "campaign_id": CAMPAIGN_ID, "manifest_sha256": sha(MANIFEST),
              "registration_commit": digest(start["registration_commit"], 40), "product_commit": digest(manifest["product_commit"], 40),
              "planned_attempts": 1, "preparation_success": int(frozen is not None),
              "joint_success": int(frozen is not None and holds["matched"] == 8 and cleanup
                                   and worker is not None and worker.get("status") == "completed"
                                   and process_status == "exited" and exit_code == 0),
              "frozen": frozen, "holdouts": holds, "usage": usage,
              "transport": transport_summary(slot / "transport.jsonl", usage["requests"]),
              "cleanup_verified": cleanup, "process_status": process_status,
              "exit_code": exit_code, "elapsed_seconds": number(process["elapsed_seconds"]),
              "worker_status": worker_status, "worker_stage": worker_stage,
              "local_failure": local_failure,
              "quality": None, "gap": None}
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
