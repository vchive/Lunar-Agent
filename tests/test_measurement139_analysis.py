"""Real retained CLI summaries: success needs the complete, bound native closure."""
from __future__ import annotations

import copy
import gc
import json
import subprocess

import pytest
from measurement139_native_support import prepare_worker
from measurement139_support import analysis

from famou.candidate_evaluation_spec import canonical_json


def rewrite(path, value):
    path.write_bytes(canonical_json(value))


def rewrite_rows(path, rows):
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))


def retained(monkeypatch, tmp_path, *, outcome="success"):
    f = prepare_worker(monkeypatch, tmp_path, outcome=outcome)
    f.worker.main()
    # The real supervisor summarizes only after the worker process exits. Close
    # this in-process fixture's unreachable native SQLite connections before
    # taking the retained snapshot, so their WAL checkpoints are not attributed
    # to read-only analysis when a later allocation triggers cyclic collection.
    gc.collect()
    identity = json.loads((f.root / "started.json").read_bytes())
    identity.pop("started_utc")
    f.runner.write_new(f.root / "finished.json", {
        **identity, "finished_utc": "2026-09-20T00:01:00+00:00",
        "planned_attempts": 1, "status": "finished",
    })
    f.runner.write_new(f.slot / "finished.json", {
        "process_status": "exited", "exit_code": 0 if f.result()["status"] == "completed" else 1,
        "cleanup_verified": True, "remaining_observed_pids": [],
        "elapsed_seconds": f.result()["elapsed_seconds"] + 0.1,
    })
    monkeypatch.setattr(analysis, "HERE", tmp_path / "spec" / "measurement")
    f.analysis.HERE.mkdir(parents=True)
    return f


def evidence_bytes(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_native_summary_is_read_only_and_publishes_once(monkeypatch, tmp_path):
    f = retained(monkeypatch, tmp_path)
    before = evidence_bytes(f.root)

    def forbidden(*_args, **_kwargs):
        pytest.fail("summary tried to execute retained source or contact a provider")

    import famou.evaluator_bundle as evaluator
    from famou import runtime
    monkeypatch.setattr(evaluator, "_snapshot_probe", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(runtime.OpenAICompatibleRuntime, "complete", forbidden)
    result = analysis.summarize(f.manifest)
    assert result["primary_success"] == result["joint_success"] == result["preparation_success"] == 1
    assert result["product"]["closure_verified"] is True
    assert result["budgets"] == {"verified": True, "ledger_complete": True, "stopped_reason": None}
    assert result["holdouts"]["matched"] == result["holdouts"]["executed"] == 8
    assert result["quality"] == 3 and result["gap"] == 0 and result["optimal"] is True
    assert evidence_bytes(f.root) == before
    serialized = json.dumps(result)
    for private in ("offline-fixture-secret", "offline.invalid", "private-generated-text", "redacted_prefix"):
        assert private not in serialized
    with pytest.raises(FileExistsError):
        analysis.summarize(f.manifest)
    assert evidence_bytes(f.root) == before


@pytest.mark.parametrize("outcome", [
    "contract_response", "contract_scope", "compiler_response", "auditor_response",
    "compiler_provider_failure", "candidate_provider_failure", "candidate_source",
])
def test_failed_native_run_retains_one_attempt_without_official_credit(monkeypatch, tmp_path, outcome):
    f = retained(monkeypatch, tmp_path, outcome=outcome)
    before = evidence_bytes(f.root)
    result = analysis.summarize(f.manifest)
    assert result["planned_attempts"] == 1
    assert result["primary_success"] == result["joint_success"] == 0
    assert result["quality"] is result["gap"] is None
    assert result["optimal"] is False
    assert evidence_bytes(f.root) == before
    if outcome == "candidate_source":
        assert result["worker_stage"] == "holdout_gate"
        assert result["preparation_success"] == 1
        assert result["holdouts"]["executed"] == 0


@pytest.mark.parametrize("mutation", [
    "guard_missing", "pending_request", "missing_request_start_clock", "missing_transport",
    "unbound_request", "token_stop", "guard_stop", "total_wall", "worker_missing", "cleanup_failed",
    "missing_ledger", "unknown_usage",
    "effective_timeout_overrun",
])
def test_complete_product_cannot_hide_incomplete_or_stopped_attempt(monkeypatch, tmp_path, mutation):
    f = retained(monkeypatch, tmp_path)
    worker = f.result()
    calls = analysis.read_rows(f.slot / "calls.jsonl")
    transport = analysis.read_rows(f.slot / "transport.jsonl")
    process = analysis.read_json(f.slot / "finished.json")
    if mutation == "guard_missing":
        worker["guard"] = None
    elif mutation == "pending_request":
        calls.pop()
        worker["guard"]["finished_requests"] -= 1
        worker["guard"]["known_usage"] = calls[-2]["known_usage"]
        worker["guard"]["usage_complete"] = False
        transport.pop()
    elif mutation == "missing_request_start_clock":
        calls[-2].pop("elapsed_seconds")
    elif mutation == "missing_transport":
        transport.pop()
    elif mutation == "unbound_request":
        transport[-1].update(stage="unbound", context_bound=False, run_id=None, task_id=None,
                             budget_id=None, max_tool_steps=None)
    elif mutation == "token_stop":
        delta = analysis.LIMITS["token_stop_threshold"]
        calls[-1]["usage"]["input_tokens"] += delta
        calls[-1]["usage"]["total_tokens"] += delta
        calls[-1]["known_usage"]["input_tokens"] += delta
        calls[-1]["known_usage"]["total_tokens"] += delta
        worker["guard"]["known_usage"] = calls[-1]["known_usage"]
    elif mutation == "guard_stop":
        worker["guard"]["stopped_reason"] = "request_limit_reached"
    elif mutation == "missing_ledger":
        calls, transport = [], []
        worker["guard"] = None
    elif mutation == "unknown_usage":
        calls[-1].update(outcome="usage_unavailable", usage=None, known_usage=calls[-3]["known_usage"])
        worker["guard"].update(stopped_reason="usage_unavailable", usage_complete=False,
                               known_usage=calls[-1]["known_usage"])
    elif mutation == "effective_timeout_overrun":
        calls[-2]["request_timeout_seconds"] = 1e-9
    elif mutation == "total_wall":
        process["elapsed_seconds"] = analysis.LIMITS["wall_seconds"]
    elif mutation == "cleanup_failed":
        process["cleanup_verified"] = False
    rewrite_rows(f.slot / "calls.jsonl", calls)
    rewrite_rows(f.slot / "transport.jsonl", transport)
    rewrite(f.slot / "finished.json", process)
    rewrite(f.slot / "worker-finished.json", worker)
    if mutation == "worker_missing":
        (f.slot / "worker-finished.json").unlink()
    result = analysis.summarize(f.manifest)
    assert result["joint_success"] == 0
    assert result["quality"] is result["gap"] is None
    if mutation != "cleanup_failed":
        assert result["primary_success"] == 0


@pytest.mark.parametrize("mutation", ["guard_count", "guard_usage", "guard_usage_bool", "guard_reason",
                                        "candidate_timeout", "contract_timeout", "request_clock", "holdout_unknown"])
def test_malformed_retained_evidence_prevents_publication(monkeypatch, tmp_path, mutation):
    f = retained(monkeypatch, tmp_path)
    worker = f.result()
    calls = analysis.read_rows(f.slot / "calls.jsonl")
    if mutation == "guard_count":
        worker["guard"]["provider_requests"] += 1
    elif mutation == "guard_usage":
        worker["guard"]["known_usage"]["total_tokens"] += 1
    elif mutation == "guard_usage_bool":
        worker["guard"]["usage_complete"] = 1
    elif mutation == "guard_reason":
        worker["guard"]["stopped_reason"] = "private-provider-text"
    elif mutation == "candidate_timeout":
        calls[-2]["request_timeout_seconds"] = 601
    elif mutation == "contract_timeout":
        calls[0]["request_timeout_seconds"] = 900
    elif mutation == "request_clock":
        calls[-2]["elapsed_seconds"] = 0
    else:
        path = f.slot / "holdouts/001.json"
        value = analysis.read_json(path)
        value["status"] = "unknown"
        rewrite(path, value)
    rewrite_rows(f.slot / "calls.jsonl", calls)
    rewrite(f.slot / "worker-finished.json", worker)
    with pytest.raises(ValueError):
        analysis.summarize(f.manifest)
    assert not (analysis.HERE.parent / "postrun").exists()


def test_summary_without_product_or_request_files_does_not_create_product_state(monkeypatch, tmp_path):
    f = prepare_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(analysis, "HERE", tmp_path / "spec/measurement")
    analysis.HERE.mkdir(parents=True)
    marker = analysis.read_json(f.root / "started.json")
    f.runner.write_new(f.root / "finished.json", marker)
    f.runner.write_new(f.slot / "finished.json", {
        "process_status": "supervisor_failed", "exit_code": None,
        "cleanup_verified": False, "remaining_observed_pids": [], "elapsed_seconds": 0,
    })
    before = evidence_bytes(f.root)
    result = analysis.summarize(f.manifest)
    assert result["planned_attempts"] == 1
    assert result["primary_success"] == result["joint_success"] == result["preparation_success"] == 0
    assert result["usage"]["usage_complete"] is False
    assert not (f.slot / "home").exists() and not (f.slot / "workspace").exists()
    assert evidence_bytes(f.root) == before


@pytest.mark.parametrize("field", ["registration_id", "attempt_id", "registration_commit"])
def test_summary_refuses_cross_bound_terminal_marker(monkeypatch, tmp_path, field):
    f = prepare_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(analysis, "HERE", tmp_path / "spec/measurement")
    analysis.HERE.mkdir(parents=True)
    marker = analysis.read_json(f.root / "started.json")
    marker[field] = "other-registration-or-attempt"
    f.runner.write_new(f.root / "finished.json", marker)
    with pytest.raises(ValueError, match="registration_binding_changed"):
        analysis.summarize(f.manifest)
    assert not (analysis.HERE.parent / "postrun").exists()


def test_optional_transport_observation_stays_unknown_without_inventing_success(monkeypatch, tmp_path):
    f = retained(monkeypatch, tmp_path)
    usage = analysis.usage_summary(f.slot / "calls.jsonl")
    path = f.slot / "transport.jsonl"
    rows = analysis.read_rows(path)
    for row in rows:
        row.update(status=None, outcome="unavailable", exchange_count=0, request_sha256=None,
                   transport_observation=None)
    rewrite_rows(path, rows)
    projected = analysis.transport_summary(f.slot / "transport.jsonl", usage["requests"])
    assert all(row["status"] is None and row["outcome"] == "unavailable" for row in projected)
    assert all(row["context_bound"] is True for row in projected)
    assert usage["requests"][0]["stage"] == "contract_compiler"
    original = copy.deepcopy(usage)
    assert "offline-fixture-secret" not in json.dumps(projected)
    assert usage == original
