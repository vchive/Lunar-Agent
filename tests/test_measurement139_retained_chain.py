"""Re-audit native synthetic artifacts, then corrupt one independent boundary."""
from __future__ import annotations

import gc
import hashlib
import json
import sqlite3

import pytest
from measurement139_native_support import prepare_worker

from famou.candidate_evaluation_spec import canonical_json


def inventory(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def completed(tmp_path, monkeypatch):
    fixture = prepare_worker(monkeypatch, tmp_path)
    assert fixture.worker.main() == 0
    # In production the worker process exits before audit. Close fixture-only
    # native Store cycles before taking the immutable retained byte inventory.
    gc.collect()
    return fixture


def rehash_trace(fixture, rows):
    digest, encoded = hashlib.sha256(), []
    for index, row in enumerate(rows, 1):
        row.update(index=index, previous_sha256=digest.hexdigest())
        raw = canonical_json(row) + b"\n"
        digest.update(raw)
        encoded.append(raw)
    (fixture.slot / "native-trace.jsonl").write_bytes(b"".join(encoded))
    anchor = {"rows": len(rows), "sha256": digest.hexdigest()}
    (fixture.slot / "native-trace-closed.json").write_bytes(canonical_json(anchor))
    worker = fixture.result()
    worker["guard"]["native_trace"] = anchor
    (fixture.slot / "worker-finished.json").write_bytes(canonical_json(worker))


def test_retained_native_closure_is_complete_and_read_only(completed, monkeypatch):
    fixture = completed
    before = inventory(fixture.slot)

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only analysis executed a provider, candidate, or evaluator")

    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.bundle_evolution.run_candidate_execution_recorded", forbidden)
    monkeypatch.setattr("famou.bundle_evolution.evaluate_candidate_execution", forbidden)
    monkeypatch.setattr("famou.controller.LocalController.__init__", forbidden)
    monkeypatch.setattr("famou.evolution.CandidateArchive.__init__", forbidden)
    monkeypatch.setattr("famou.evolution.CandidateArchive._recover_seed_publication", forbidden)
    result = fixture.analysis.inspect_product(fixture.slot)
    assert result["closure_verified"] is result["primary_valid_completion"] is True
    assert result["completed_candidates"] == 2
    assert [row["stage"] for row in result["stage_receipts"]] == [
        "preparation", "candidate_generation", "candidate_execution", "independent_scoring",
        "candidate_generation", "candidate_execution", "independent_scoring", "selection", "parent_delivery",
    ]
    assert result["selected_candidate_id"] in [row["candidate_id"] for row in result["native_candidates"]]
    assert [row["request_indices"] for row in result["native_candidates"]] == [[4], [5]]
    assert inventory(fixture.slot) == before


@pytest.mark.parametrize("drift", [
    "missing_generation", "missing_selection", "trace_order", "trace_late", "trace_overlap",
    "trace_candidate", "trace_budget", "trace_execution", "trace_score", "trace_preparation",
    "missing_anchor", "worker_anchor", "wire_identity", "missing_request", "unbound_request",
    "generation_store_deleted", "generation_store_failed", "output", "source", "score",
    "trace_preparation_time", "trace_after_worker", "seed_recovery",
])
def test_retained_chain_rejects_missing_or_conflicting_evidence_after_rehash(completed, drift):
    fixture = completed
    slot = fixture.slot
    rows = list(map(json.loads, (slot / "native-trace.jsonl").read_bytes().splitlines()))
    if drift.startswith("trace_") or drift in {"missing_generation", "missing_selection"}:
        if drift == "missing_generation":
            rows.pop(1)
        elif drift == "missing_selection":
            rows.pop(-2)
        elif drift == "trace_order":
            rows[2], rows[3] = rows[3], rows[2]
        elif drift == "trace_late":
            rows[-1]["finished_at"] = 2401
        elif drift == "trace_overlap":
            rows[-1]["started_at"] = rows[0]["started_at"]
        elif drift == "trace_preparation_time":
            rows[0]["started_at"] = rows[0]["finished_at"] = 0
        elif drift == "trace_after_worker":
            rows[-1]["finished_at"] = fixture.result()["guard"]["elapsed_seconds"] + 1
        elif drift == "trace_candidate":
            rows[1]["binding"]["candidate_id"] = "forged"
        elif drift == "trace_budget":
            rows[1]["binding"]["budget_id"] = "unrelated-budget"
        elif drift == "trace_execution":
            rows[2]["binding"]["completion_sha256"] = "1" * 64
        elif drift == "trace_score":
            rows[3]["binding"]["evaluation_sha256"] = "1" * 64
        else:
            rows[0]["binding"]["payload_sha256"] = "1" * 64
        rehash_trace(fixture, rows)
    elif drift == "missing_anchor":
        (slot / "native-trace-closed.json").unlink()
    elif drift == "worker_anchor":
        worker = fixture.result()
        worker["guard"]["native_trace"]["sha256"] = "1" * 64
        (slot / "worker-finished.json").write_bytes(canonical_json(worker))
    elif drift in {"wire_identity", "unbound_request"}:
        transport = list(map(json.loads, (slot / "transport.jsonl").read_bytes().splitlines()))
        if drift == "wire_identity":
            transport[3]["task_id"] = "unrelated-task"
        else:
            transport.pop()
        (slot / "transport.jsonl").write_bytes(b"".join(canonical_json(row) + b"\n" for row in transport))
    elif drift == "missing_request":
        calls = list(map(json.loads, (slot / "calls.jsonl").read_bytes().splitlines()))
        (slot / "calls.jsonl").write_bytes(b"".join(canonical_json(row) + b"\n" for row in calls[:-2]))
    elif drift.startswith("generation_store"):
        with sqlite3.connect(slot / "home/state.db") as connection:
            if drift == "generation_store_deleted":
                connection.execute("DELETE FROM events WHERE type='agent_candidate_generation'")
            else:
                event_id, payload = connection.execute(
                    "SELECT id,payload FROM events WHERE type='agent_candidate_generation' LIMIT 1",
                ).fetchone()
                payload = json.loads(payload)
                payload["outcome"], payload["completion"] = "failed", False
                connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), event_id))
    elif drift == "output":
        (slot / "workspace/output/result.json").write_text('{"value":2}')
    elif drift == "source":
        path = next((slot / "workspace/evolution-run/evolution/candidates").glob("*/solve/helper.py"))
        path.write_text("def choose(limit):\n    return 0\n")
    elif drift == "seed_recovery":
        (slot / "workspace/evolution-run/.evolution-seed-stage-v1").mkdir()
    else:
        path = next((slot / "workspace/evolution-run/evolution/bundle-attempts").glob(
            "*/evaluations/*/report.json",
        ))
        path.write_text('{}')
    before = inventory(slot)
    result = fixture.analysis.inspect_product(slot)
    assert result["primary_valid_completion"] is False
    assert result["closure_verified"] is False
    assert result["quality"] is None
    assert inventory(slot) == before
