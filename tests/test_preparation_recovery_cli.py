"""Public CLI retains failed evaluator preparation and explicitly resumes the same contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_conversational_automatic_bundle import automatic_setup

from lunar_evolution import cli
from lunar_evolution.store import Store

PRIVATE_ERROR = "api_key=do-not-retain-this-secret private provider detail"


def run_cli(capsys, args):
    code = cli.main(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out else None
    return code, payload, captured.err


def runtime_calls(runtime):
    return (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls,
            runtime.generator_calls, runtime.isolated_calls)


def snapshot(store, run_id, workspace):
    return (
        store.list_events(run_id), store.list_artifacts(run_id),
        {str(path.relative_to(workspace)): path.read_bytes()
         for path in workspace.rglob("*") if path.is_file()},
    )


def fail_stage(monkeypatch, runtime, stage, error_type=TimeoutError):
    original, attempts = runtime.run, []
    marker = "frozen local evaluator bundle" if stage == "evaluator_compile" else "adversarial evaluator auditor"

    def failed(prompt, workspace, timeout=None):
        if marker in prompt:
            attempts.append(stage)
            raise error_type(PRIVATE_ERROR)
        return original(prompt, workspace, timeout)

    monkeypatch.setattr(runtime, "run", failed)
    return original, attempts


def followup(tmp_path, run_id, command="resume"):
    args = ["resume", run_id] if command == "resume" else ["solve", "--resume", "--run-id", run_id]
    return [*args, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"]


def observations(store, run_id, kind=None):
    return [event for event in store.list_events(run_id)
            if event["type"].startswith("bundle_preparation_")
            and (kind is None or event["type"] == kind)]


@pytest.mark.parametrize("stage", ["evaluator_compile", "evaluator_audit"])
@pytest.mark.parametrize("error_type", [TimeoutError, RuntimeError])
def test_failed_preparation_returns_safe_parent_json_status_and_rejects_stray_answer(
    tmp_path, monkeypatch, capsys, stage, error_type,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    _, attempts = fail_stage(monkeypatch, runtime, stage, error_type)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    assert failed["status"] == "failed" and failed["run_status"] == "running"
    assert failed["input_request"] is None and failed["plan"] is not None
    preparation = failed["evolution"]["preparation"]
    assert preparation["status"] == "failed" and preparation["stage"] == stage
    assert preparation["error_category"] == "runtime_error" and preparation["recoverable"] is True
    assert preparation["parent_run_id"] == failed["run_id"]
    assert "resume" in preparation["resume_hint"]
    assert attempts == [stage] and runtime.contract_calls == 1 and runtime.generator_calls == 0
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    assert (workspace / "solve/contract.json").is_file()
    assert not (workspace / "evolution-run").exists()
    records = observations(store, failed["run_id"])
    assert [event["type"] for event in records] == ["bundle_preparation_started", "bundle_preparation_failed"]
    assert records[0]["payload"]["attempt_id"] == records[1]["payload"]["attempt_id"]
    assert PRIVATE_ERROR not in json.dumps([failed, records])

    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    code, status, stderr = run_cli(capsys, ["status", failed["run_id"], "--home", str(tmp_path / "home"), "--json"])
    assert code == 0 and stderr == ""
    assert status["evolution"]["preparation"] == preparation
    assert status["reason_code"] == failed["reason_code"] == "preparation_runtime_error"
    assert status["input_request"] is None
    assert cli.main(["status", failed["run_id"], "--home", str(tmp_path / "home")]) == 0
    text = capsys.readouterr().out
    assert "evaluator_preparation: failed" in text and f"{stage}: runtime_error" in text
    assert "status_reason: preparation_runtime_error" in text
    assert "resume" in text and PRIVATE_ERROR not in text
    code, answer, stderr = run_cli(capsys, ["answer", failed["run_id"], "please continue",
                                          "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"])
    assert code == 2 and answer is None
    assert "not awaiting input" in json.loads(stderr)["error"]
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == calls and attempts == [stage]
    assert not list(workspace.rglob("input-answer.json"))


@pytest.mark.parametrize("stage", ["evaluator_compile", "evaluator_audit"])
@pytest.mark.parametrize("command", ["resume", "solve"])
def test_explicit_resume_reuses_contract_delivers_and_terminal_repeat_is_idempotent(
    tmp_path, monkeypatch, capsys, stage, command,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original, attempts = fail_stage(monkeypatch, runtime, stage)
    code, failed, _ = run_cli(capsys, args)
    assert code == 1 and attempts == [stage]
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    contract = (workspace / "solve/contract.json").read_bytes()
    monkeypatch.setattr(runtime, "run", original)
    continuation = followup(tmp_path, failed["run_id"], command)
    code, resumed, stderr = run_cli(capsys, continuation)
    assert code == 0 and stderr == ""
    assert resumed["run_id"] == failed["run_id"] and resumed["status"] == "succeeded"
    assert resumed["evolution"]["preparation"]["status"] == "prepared"
    assert resumed["evolution"]["materialization"]["status"] == "succeeded"
    assert resumed["evolution"]["result"]["best_score"] == 9
    assert (workspace / "solve/contract.json").read_bytes() == contract
    assert runtime.contract_calls == 1 and runtime.generator_calls == 4
    assert len(observations(store, failed["run_id"], "bundle_preparation_started")) == 2
    assert len(observations(store, failed["run_id"], "bundle_preparation_failed")) == 1
    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    code, repeated, stderr = run_cli(capsys, continuation)
    assert code == 0 and stderr == ""
    assert repeated["evolution"] == resumed["evolution"]
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == calls


@pytest.mark.parametrize("stage", ["evaluator_compile", "evaluator_audit"])
def test_clarification_answer_retains_parent_json_when_evaluator_preparation_fails(
    tmp_path, monkeypatch, capsys, stage,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    code, waiting, _ = run_cli(capsys, args)
    assert code == 0 and waiting["status"] == "awaiting_input"
    _, attempts = fail_stage(monkeypatch, runtime, stage)
    code, failed, stderr = run_cli(capsys, ["answer", waiting["run_id"], "maximize value",
                                          "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"])
    assert code == 1 and stderr == ""
    assert failed["run_id"] == waiting["run_id"] and failed["status"] == "failed"
    assert failed["run_status"] == "running" and failed["input_request"] is None
    assert Store(tmp_path / "home/state.db").pending_input(failed["run_id"]) is None
    assert failed["evolution"]["preparation"]["stage"] == stage
    assert failed["evolution"]["preparation"]["recoverable"] is True
    assert attempts == [stage] and runtime.contract_calls == 2 and runtime.generator_calls == 0
    assert PRIVATE_ERROR not in json.dumps(failed)


def test_input_drift_after_failure_is_unrecoverable_and_resume_makes_no_calls(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original, attempts = fail_stage(monkeypatch, runtime, "evaluator_compile")
    code, failed, _ = run_cli(capsys, args)
    assert code == 1 and attempts == ["evaluator_compile"]
    workspace, store = Path(failed["workspace"]), Store(tmp_path / "home/state.db")
    (workspace / "data/raw/value").write_bytes(b"20")
    monkeypatch.setattr(runtime, "run", original)
    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    code, status, stderr = run_cli(capsys, ["status", failed["run_id"], "--home", str(tmp_path / "home"), "--json"])
    assert code == 0 and stderr == ""
    preparation = status["evolution"]["preparation"]
    assert preparation["recoverable"] is False and preparation["error_category"] == "validation_error"
    assert "resume_hint" not in preparation
    code, resumed, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code == 2 and resumed is None and json.loads(stderr)["error"]
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == calls


def test_legacy_awaiting_input_without_question_corrected_only_on_explicit_continuation(
    tmp_path, monkeypatch, capsys,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    _, attempts = fail_stage(monkeypatch, runtime, "evaluator_compile")
    code, failed, _ = run_cli(capsys, args)
    assert code == 1
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = 'awaiting_input' WHERE id = ?", (failed["run_id"],))
        connection.execute("DELETE FROM events WHERE run_id = ? AND type LIKE 'bundle_preparation_%'", (failed["run_id"],))
    assert store.pending_input(failed["run_id"]) is None
    before = snapshot(store, failed["run_id"], workspace)
    code, status, _ = run_cli(capsys, ["status", failed["run_id"], "--home", str(tmp_path / "home"), "--json"])
    assert code == 0 and status["run"]["status"] == "awaiting_input"
    assert snapshot(store, failed["run_id"], workspace) == before
    code, continued, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code == 1 and stderr == ""
    assert continued["run_status"] == "running" and continued["status"] == "failed"
    assert continued["input_request"] is None
    assert store.get_run(failed["run_id"]).status.value == "running"
    assert runtime.contract_calls == 1 and attempts == ["evaluator_compile", "evaluator_compile"]


def test_cancelled_parent_never_offers_resume_or_calls_models_again(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original, _ = fail_stage(monkeypatch, runtime, "evaluator_compile")
    _, failed, _ = run_cli(capsys, args)
    store = Store(tmp_path / "home/state.db")
    assert store.cancel_run(failed["run_id"])
    monkeypatch.setattr(runtime, "run", original)
    calls = runtime_calls(runtime)
    code, status, _ = run_cli(capsys, ["status", failed["run_id"], "--home", str(tmp_path / "home"), "--json"])
    assert code == 0 and status["run"]["status"] == "cancelled"
    preparation = status["evolution"]["preparation"]
    assert preparation["error_category"] == "cancelled" and preparation["recoverable"] is False
    assert "resume_hint" not in preparation
    code, _, _ = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code != 0 and runtime_calls(runtime) == calls


@pytest.mark.parametrize("corruption", [
    "parent", "attempt", "duplicate_start", "schema", "status", "extra_field",
])
def test_corrupt_failed_attempt_is_rejected_before_explicit_resume(
    tmp_path, monkeypatch, capsys, corruption,
):
    """Recovery admission must bind the failed observation before opening another attempt."""
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    _, attempts = fail_stage(monkeypatch, runtime, "evaluator_compile")
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == "" and attempts == ["evaluator_compile"]

    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    records = observations(store, failed["run_id"])
    start, failure = records
    payload = copy.deepcopy(failure["payload"])
    if corruption == "parent":
        payload["parent_run_id"] = "different-parent"
    elif corruption == "attempt":
        payload["attempt_id"] = "preparation-" + "f" * 32
    elif corruption == "schema":
        payload["schema_version"] = "999"
    elif corruption == "status":
        payload["status"] = "started"
    elif corruption == "extra_field":
        payload["unexpected_detail"] = "unvalidated private provider detail"
    elif corruption == "duplicate_start":
        with store._connect() as connection:
            connection.execute(
                "INSERT INTO events (id,run_id,task_id,type,payload,created_at) VALUES (?,?,?,?,?,?)",
                (
                    "duplicate-preparation-start", failed["run_id"], None,
                    "bundle_preparation_started", json.dumps(start["payload"]),
                    "2100-01-01T00:00:01",
                ),
            )
            connection.execute("UPDATE events SET created_at = ? WHERE id = ?",
                               ("2100-01-01T00:00:00", start["id"]))
            connection.execute("UPDATE events SET created_at = ? WHERE id = ?",
                               ("2100-01-01T00:00:02", failure["id"]))
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), failure["id"]))

    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    code, resumed, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code == 2 and resumed is None
    assert json.loads(stderr)["error"]
    assert runtime_calls(runtime) == calls and attempts == ["evaluator_compile"]
    expected_starts = 2 if corruption == "duplicate_start" else 1
    assert len(observations(store, failed["run_id"], "bundle_preparation_started")) == expected_starts
    assert snapshot(store, failed["run_id"], workspace) == before
