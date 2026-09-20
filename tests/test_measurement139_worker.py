"""One consumed worker slot runs the actual native CLI with offline responses."""
from __future__ import annotations

import json
import sqlite3
import stat

import pytest
from measurement139_native_support import prepare_worker

from famou import cli


def test_native_cli_text_output_preparation_delivery_and_eight_holdouts(tmp_path, monkeypatch, capsys):
    fixture = prepare_worker(monkeypatch, tmp_path)
    assert fixture.worker.main() == 0
    result = fixture.result()
    assert result["status"] == "completed" and result["stage"] == "finished"
    assert result["native_exit_code"] == 0
    assert result["solve_error_class"] is result["preparation_error_class"] is result["error_class"] is None
    assert len(result["holdouts"]) == 8 and all(row["matched"] for row in result["holdouts"])
    assert len(list((fixture.slot / "holdouts").glob("*.json"))) == 8
    retained_cli = json.loads((fixture.slot / "cli.json").read_text(encoding="utf-8"))
    assert retained_cli["status"] == retained_cli["run_status"] == "succeeded"
    assert retained_cli["evolution"]["result"]["evaluated_candidates"] == 2
    assert stat.S_IMODE((fixture.slot / "cli.json").stat().st_mode) == 0o600
    assert len(fixture.requests) == result["guard"]["provider_requests"] == 5
    starts = [row for row in map(json.loads, (fixture.slot / "calls.jsonl").read_text().splitlines())
              if row["kind"] == "request_started"]
    assert [round(row["request_timeout_seconds"]) for row in starts] == [600, 900, 900, 600, 600]
    transport = list(map(json.loads, (fixture.slot / "transport.jsonl").read_text().splitlines()))
    assert [row["stage"] for row in transport] == [
        "contract_compiler", "evaluator_compiler", "evaluator_auditor",
        "candidate_generation", "candidate_generation",
    ]
    assert all(row["exchange_count"] == 1 and row["status"] == 200 for row in transport)
    assert fixture.analysis.inspect_product(fixture.slot)["primary_valid_completion"] is True
    assert fixture.provider_calls == [{
        "requested_model": "glm-5.2", "expected": fixture.manifest["provider_safe_metadata"],
    }]
    retained = (fixture.slot / "worker-finished.json").read_bytes()
    assert fixture.worker.main() == 1
    assert (fixture.slot / "worker-finished.json").read_bytes() == retained
    assert len(fixture.requests) == 5 and len(fixture.provider_calls) == 1
    assert fixture.provider.api_key not in capsys.readouterr().out


@pytest.mark.parametrize("outcome,prepared,requests", [
    ("contract_response", False, 1), ("compiler_response", False, 2),
    ("auditor_response", False, 3), ("compiler_provider_failure", False, 2),
    ("candidate_source", True, 4), ("candidate_provider_failure", True, 4),
])
def test_native_failures_do_not_run_holdouts_or_reuse_slot(
    tmp_path, monkeypatch, outcome, prepared, requests,
):
    fixture = prepare_worker(monkeypatch, tmp_path, outcome=outcome)
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["status"] == "failed"
    assert (result["frozen"] is not None) is prepared
    assert result["stage"] == ("holdout_gate" if prepared else "preparation_check")
    assert result["holdouts"] == [] and not (fixture.slot / "holdout-workspaces").exists()
    assert len(fixture.requests) == requests
    assert "private-invalid" not in json.dumps(result)
    assert "private-candidate" not in json.dumps(result)
    assert "private-provider" not in json.dumps(result)
    retained = (fixture.slot / "worker-finished.json").read_bytes()
    assert fixture.worker.main() == 1
    assert (fixture.slot / "worker-finished.json").read_bytes() == retained
    assert len(fixture.requests) == requests and len(fixture.provider_calls) == 1


@pytest.mark.parametrize("place", ["root", "slot"])
@pytest.mark.parametrize("kind", ["admission", "started"])
@pytest.mark.parametrize("drift", ["missing", "extra", "identity", "digest", "timestamp"])
def test_invalid_markers_reject_before_provider_and_preserve_consumed_failure(
    tmp_path, monkeypatch, place, kind, drift,
):
    fixture = prepare_worker(monkeypatch, tmp_path)
    path = getattr(fixture, place) / f"{kind}.json"
    original = path.read_bytes()
    marker = json.loads(original)
    if drift == "missing":
        marker.pop("registration_id")
    elif drift == "extra":
        marker["unknown"] = "not-admitted"
    elif drift == "identity":
        marker["campaign_id"] = "other-campaign"
    elif drift == "digest":
        marker["manifest_sha256"] = "0" * 64
    else:
        marker["admitted_utc" if kind == "admission" else "started_utc"] = ""
    path.write_text(json.dumps(marker), encoding="utf-8")
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["stage"] == "setup" and result["error_class"] == "ValueError"
    assert result["guard"] is None and fixture.provider_calls == fixture.requests == []
    assert not (fixture.slot / "worker-started.json").exists()
    terminal = (fixture.slot / "worker-finished.json").read_bytes()
    path.write_bytes(original)
    assert fixture.worker.main() == 1
    assert fixture.provider_calls == fixture.requests == []
    assert (fixture.slot / "worker-finished.json").read_bytes() == terminal


@pytest.mark.parametrize("field,key,value", [
    ("budgets", "wall_seconds", 2401), ("budgets", "candidate_steps", True),
    ("budgets", "max_requests", 0), ("population", "members", 2),
    ("population", "islands", True), ("runtime_options", "workers", 2),
    ("runtime_options", "agent_loop", 1), ("runtime_options", "allow_exec", True),
    ("runtime_options", "extra", False), ("runtime_options", "launch_argv", ["solve"]),
])
def test_launch_drift_rejected_before_provider(tmp_path, monkeypatch, field, key, value):
    fixture = prepare_worker(monkeypatch, tmp_path)
    fixture.manifest[field][key] = value
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["stage"] == "setup" and result["error_class"] == "ValueError"
    assert result["guard"] is None and fixture.provider_calls == fixture.requests == []
    assert not (fixture.slot / "cli.json").exists()


@pytest.mark.parametrize("field", ["budgets", "population", "runtime_options"])
@pytest.mark.parametrize("shape", ["missing", "wrong_type", "missing_key"])
def test_missing_launch_settings_rejected_before_provider(tmp_path, monkeypatch, field, shape):
    fixture = prepare_worker(monkeypatch, tmp_path)
    if shape == "missing":
        fixture.manifest.pop(field)
    elif shape == "wrong_type":
        fixture.manifest[field] = []
    else:
        fixture.manifest[field].pop(next(iter(fixture.manifest[field])))
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["stage"] == "setup" and result["error_class"] == "ValueError"
    assert fixture.provider_calls == fixture.requests == []


@pytest.mark.parametrize("index", [True, "1", 0, 2])
def test_started_slot_index_is_exact_integer_one(tmp_path, monkeypatch, index):
    fixture = prepare_worker(monkeypatch, tmp_path)
    path = fixture.slot / "started.json"
    marker = json.loads(path.read_text())
    marker["index"] = index
    path.write_text(json.dumps(marker), encoding="utf-8")
    assert fixture.worker.main() == 1
    assert fixture.result()["error_class"] == "ValueError"
    assert fixture.provider_calls == fixture.requests == []


@pytest.mark.parametrize("artifact", ["root-finished", "slot-finished", "worker-started", "worker-finished"])
def test_consumed_slot_rejected_before_provider(tmp_path, monkeypatch, artifact):
    fixture = prepare_worker(monkeypatch, tmp_path)
    directory = fixture.root if artifact.startswith("root-") else fixture.slot
    name = "finished.json" if artifact.endswith("-finished") and not artifact.startswith("worker-") else f"{artifact}.json"
    (directory / name).write_text("{}\n", encoding="utf-8")
    assert fixture.worker.main() == 1
    assert fixture.provider_calls == fixture.requests == []
    assert not (fixture.slot / "cli.json").exists()


@pytest.mark.parametrize("damage", ["primary_completion", "output_artifact", "source_evidence"])
def test_missing_native_delivery_proof_blocks_holdouts(tmp_path, monkeypatch, damage):
    fixture = prepare_worker(monkeypatch, tmp_path)
    original_preparation = fixture.worker.verified_preparation

    def after_preparation(slot):
        prepared = original_preparation(slot)
        retained_cli = json.loads((slot / "cli.json").read_text(encoding="utf-8"))
        if damage == "primary_completion":
            retained_cli["status"] = "failed"
            (slot / "cli.json").write_text(json.dumps(retained_cli), encoding="utf-8")
        elif damage == "output_artifact":
            with sqlite3.connect(slot / "home/state.db") as database:
                database.execute("DELETE FROM artifacts WHERE kind = 'output'")
        else:
            delivery = retained_cli["evolution"]["materialization"]["delivery_path"]
            (slot / "workspace" / delivery / "evaluation/source-checks.json").write_text("{}\n")
        return prepared

    monkeypatch.setattr(fixture.worker, "verified_preparation", after_preparation)
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["frozen"] is not None and result["stage"] == "holdout_gate"
    assert result["holdouts"] == [] and not (fixture.slot / "holdout-workspaces").exists()
    assert len(fixture.requests) == 5


def test_native_exception_records_bounded_failure_without_retry(tmp_path, monkeypatch):
    fixture = prepare_worker(monkeypatch, tmp_path)

    def failure(_args):
        # Exercise the real output emitter even on an interrupted native path.
        cli._emit({"status": "failed", "message": "private-native-diagnostic"}, True)
        raise RuntimeError("private-native-exception")

    monkeypatch.setattr(cli, "main", failure)
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["native_exit_code"] is None and result["solve_error_class"] == "RuntimeError"
    assert result["holdouts"] == []
    assert "private-native" not in json.dumps(result)
    assert json.loads((fixture.slot / "cli.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("closure", [None, False, "unknown", 1])
def test_holdout_gate_requires_explicit_verified_closure(tmp_path, monkeypatch, closure):
    fixture = prepare_worker(monkeypatch, tmp_path)
    product = {
        "product_success": True, "primary_valid_completion": True,
        "preparation_verified": True, "contract_verified": True,
        "delivery_verified": True, "source_evidence_verified": True,
        "source_check_validity": True, "source_python_count": 2,
    }
    if closure is not None:
        product["closure_verified"] = closure
    monkeypatch.setattr(fixture.worker, "inspect_product", lambda _slot: product)
    assert fixture.worker._holdout_gate(fixture.slot) is False


def test_local_holdouts_obey_original_deadline(tmp_path, monkeypatch):
    fixture = prepare_worker(monkeypatch, tmp_path)
    original_preparation = fixture.worker.verified_preparation
    clock = fixture.worker.time.monotonic

    def after_deadline(slot):
        prepared = original_preparation(slot)
        expired = clock() + fixture.manifest["budgets"]["wall_seconds"] + 1
        monkeypatch.setattr(fixture.worker.time, "monotonic", lambda: expired)
        return prepared

    monkeypatch.setattr(fixture.worker, "verified_preparation", after_deadline)
    assert fixture.worker.main() == 1
    result = fixture.result()
    assert result["frozen"] is not None and result["holdouts"] == []
    assert result["stage"] == "holdouts" and result["error_class"] == "ValueError"
    assert not (fixture.slot / "holdout-workspaces").exists()
