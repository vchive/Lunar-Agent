"""Unsupported evidence scopes stop automatic solve with durable, safe CLI diagnostics."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_conversational_automatic_bundle import automatic_setup
from test_preparation_recovery_cli import followup, observations, run_cli, runtime_calls, snapshot

from lunar_evolution import cli
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.store import Store

DETAILS = [
    {"id": "two-source-files", "verification_scope": "source"},
    {"id": "actually-read-input", "verification_scope": "execution"},
]


def unsupported_setup(tmp_path, monkeypatch, *, clarify=False):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=clarify)
    payload = runtime.contract.to_dict()
    payload["hard_constraints"][0]["verification_scope"] = "output"
    payload["hard_constraints"].append({
        "id": "two-source-files", "description": "Deliver at least two source files.",
        "source": "user_confirmed", "verification": "partial", "result_fields": [],
        "verification_scope": "source",
    })
    payload["soft_constraints"] = [{
        "id": "actually-read-input", "description": "Read the input in the executed program.",
        "source": "user_confirmed", "verification": "solver", "result_fields": [],
        "verification_scope": "execution",
    }]
    runtime.contract = AlgorithmProblemContract.from_dict(payload)
    return runtime, args


def assert_no_evaluator_or_child(store, run_id, workspace):
    for name in (".evaluator-compiler", ".evaluator-auditor", "evaluator-bundle", "bundle-profile.json", "evolution-run"):
        assert not (workspace / name).exists()
    assert not list(workspace.glob(".evaluator-bundle-*"))
    assert not any(event["type"] in {
        "bundle_profile_prepared", "evolution_child_linked", "evolved_candidate_materialized",
        "bundle_materialized", "candidate_generated",
    } for event in store.list_events(run_id))
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def assert_capability_preparation(preparation):
    assert preparation["status"] == "failed" and preparation["stage"] == "capability_check"
    assert preparation["error_category"] == "unsupported_verification"
    assert preparation["recoverable"] is False
    assert preparation["unsupported_constraints"] == DETAILS
    assert "resume_hint" not in preparation
    assert "verify outputs only" in preparation["capability_hint"]
    assert "independent source or execution checkers" in preparation["capability_hint"]


@pytest.mark.parametrize("command", ["resume", "solve"])
def test_solve_and_readonly_status_keep_scope_failure_and_explicit_resume_makes_no_model_calls(
    tmp_path, monkeypatch, capsys, command,
):
    runtime, args = unsupported_setup(tmp_path, monkeypatch)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    assert failed["status"] == "failed" and failed["run_status"] == "running"
    assert failed["input_request"] is None and failed["plan"] is not None
    preparation = failed["evolution"]["preparation"]
    assert_capability_preparation(preparation)
    assert runtime_calls(runtime) == (1, 0, 0, 0, 1)
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    contract = (workspace / "solve/contract.json").read_bytes()
    assert json.loads(contract) == runtime.contract.to_dict()
    assert store.get_current_plan(failed["run_id"]).algorithm_problem == runtime.contract.to_dict()
    records = observations(store, failed["run_id"])
    assert [event["type"] for event in records] == ["bundle_preparation_started", "bundle_preparation_failed"]
    assert records[0]["payload"]["attempt_id"] == records[1]["payload"]["attempt_id"]
    assert records[1]["payload"]["unsupported_constraints"] == DETAILS
    assert "capability_hint" not in records[1]["payload"]
    assert_no_evaluator_or_child(store, failed["run_id"], workspace)

    before = snapshot(store, failed["run_id"], workspace)
    status_args = ["status", failed["run_id"], "--home", str(tmp_path / "home")]
    code, status, stderr = run_cli(capsys, [*status_args, "--json"])
    assert code == 0 and stderr == ""
    assert status["evolution"]["preparation"] == preparation and status["input_request"] is None
    assert cli.main(status_args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    for detail in DETAILS:
        assert f"{detail['id']} ({detail['verification_scope']})" in captured.out
    assert "capability_check: unsupported_verification" in captured.out
    assert "verify outputs only" in captured.out
    assert "resume" not in captured.out
    assert snapshot(store, failed["run_id"], workspace) == before

    code, resumed, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"], command))
    assert code == 1 and stderr == ""
    assert resumed["run_id"] == failed["run_id"] and resumed["status"] == "failed"
    assert_capability_preparation(resumed["evolution"]["preparation"])
    assert runtime_calls(runtime) == (1, 0, 0, 0, 1)
    assert (workspace / "solve/contract.json").read_bytes() == contract
    assert_no_evaluator_or_child(store, failed["run_id"], workspace)


def test_clarification_answer_retains_the_compiled_unsupported_contract_without_evaluator_calls(
    tmp_path, monkeypatch, capsys,
):
    runtime, args = unsupported_setup(tmp_path, monkeypatch, clarify=True)
    code, waiting, stderr = run_cli(capsys, args)
    assert code == 0 and stderr == "" and waiting["status"] == "awaiting_input"
    code, failed, stderr = run_cli(capsys, [
        "answer", waiting["run_id"], "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ])
    assert code == 1 and stderr == ""
    assert failed["run_id"] == waiting["run_id"] and failed["input_request"] is None
    assert_capability_preparation(failed["evolution"]["preparation"])
    assert runtime_calls(runtime) == (2, 0, 0, 0, 2)
    store = Store(tmp_path / "home/state.db")
    assert store.pending_input(failed["run_id"]) is None
    assert_no_evaluator_or_child(store, failed["run_id"], Path(failed["workspace"]))


@pytest.mark.parametrize("corruption", [
    "missing", "empty", "wrong_scope", "wrong_id", "duplicate", "extra_field",
    "string", "null", "recoverable", "wrong_stage",
])
def test_status_revalidates_persisted_scope_details_and_never_echoes_malformed_claims(
    tmp_path, monkeypatch, capsys, corruption,
):
    runtime, args = unsupported_setup(tmp_path, monkeypatch)
    code, failed, _ = run_cli(capsys, args)
    assert code == 1
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    event = observations(store, failed["run_id"], "bundle_preparation_failed")[0]
    payload = event["payload"]
    marker = "private-provider-diagnostic-must-not-be-echoed"
    if corruption == "missing":
        del payload["unsupported_constraints"]
    elif corruption == "empty":
        payload["unsupported_constraints"] = []
    elif corruption == "wrong_scope":
        payload["unsupported_constraints"][0]["verification_scope"] = "execution"
    elif corruption == "wrong_id":
        payload["unsupported_constraints"][0]["id"] = marker
    elif corruption == "duplicate":
        payload["unsupported_constraints"].append(payload["unsupported_constraints"][0])
    elif corruption == "extra_field":
        payload["unsupported_constraints"][0]["provider_error"] = marker
    elif corruption == "string":
        payload["unsupported_constraints"] = marker
    elif corruption == "null":
        payload["unsupported_constraints"] = None
    elif corruption == "recoverable":
        payload["recoverable"] = True
    else:
        payload["stage"] = "evaluator_compile"
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), event["id"]))
    before = snapshot(store, failed["run_id"], workspace)
    args = ["status", failed["run_id"], "--home", str(tmp_path / "home")]
    code, status, stderr = run_cli(capsys, [*args, "--json"])
    assert code == 0 and stderr == ""
    preparation = status["evolution"]["preparation"]
    assert preparation["error_category"] == "validation_error" and preparation["recoverable"] is False
    assert "unsupported_constraints" not in preparation
    assert "capability_hint" not in preparation and "resume_hint" not in preparation
    assert marker not in json.dumps(status)
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and marker not in captured.out
    assert "unsupported_constraint:" not in captured.out
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == (1, 0, 0, 0, 1)


@pytest.mark.parametrize("terminal", ["cancelled", "failed"])
def test_terminal_parent_cannot_restart_unsupported_preparation(tmp_path, monkeypatch, capsys, terminal):
    runtime, args = unsupported_setup(tmp_path, monkeypatch)
    code, failed, _ = run_cli(capsys, args)
    assert code == 1
    store, workspace = Store(tmp_path / "home/state.db"), Path(failed["workspace"])
    if terminal == "cancelled":
        assert store.cancel_run(failed["run_id"])
    else:
        assert store.fail_budget(failed["run_id"], "max_attempts", 2, 1, "fixture ceiling")
    before = snapshot(store, failed["run_id"], workspace)
    code, status, stderr = run_cli(capsys, [
        "status", failed["run_id"], "--home", str(tmp_path / "home"), "--json",
    ])
    assert code == 0 and stderr == "" and status["run"]["status"] == terminal
    preparation = status["evolution"]["preparation"]
    assert preparation["recoverable"] is False and "resume_hint" not in preparation
    if terminal == "cancelled":
        assert preparation["error_category"] == "cancelled"
        assert "unsupported_constraints" not in preparation and "capability_hint" not in preparation
    code, _, _ = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code != 0
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == (1, 0, 0, 0, 1)
    assert_no_evaluator_or_child(store, failed["run_id"], workspace)
