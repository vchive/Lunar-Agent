"""Bounded read-only observations and terminal precedence for automatic solves."""

from __future__ import annotations

import json

import pytest

from lunar_evolution import cli
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionObservation,
    solve_execution_status,
)
from lunar_evolution.models import RunStatus, TaskStatus
from lunar_evolution.store import Store

FIELDS = {
    "schema_version", "execution_id", "scope", "policy_seconds", "policy_origin",
    "stage", "state", "stopping_reason",
}


def _observed_run(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("automatic solve", tmp_path / "run")
    store.append_event(run.id, "evolution_requested", {
        "bundle_mode": "compiled", "automatic_lifecycle_version": 1,
        "solve_wall_timeout": 30.0, "solve_wall_timeout_source": "explicit",
    })
    task = store.ensure_orchestration_task(run.id, title="Orchestrate", prompt="evolve and deliver")
    attempt = store.claim_orchestration_task(task.id, "automatic-solve")
    assert attempt is not None
    observation = SolveExecutionObservation(store, run.id, 30.0)
    return store, store.get_run(run.id), task, attempt, observation


@pytest.mark.parametrize("timeout", [None, 300.0])
def test_solve_and_status_expose_only_bounded_read_only_observation(
    tmp_path, monkeypatch, capsys, timeout,
):
    from test_conversational_automatic_bundle import automatic_setup

    _runtime, args = automatic_setup(tmp_path, monkeypatch)
    if timeout is not None:
        args.extend(["--solve-wall-timeout", str(timeout)])
    assert cli.main(args) == 0
    solved = json.loads(capsys.readouterr().out)
    observed = solved["solve_execution"]
    assert set(observed) == FIELDS
    assert observed["state"] == "terminal"
    assert observed["stopping_reason"] == "completed"
    assert observed["stage"] == "delivery"
    assert observed["scope"] == "active_execution"
    assert observed["policy_seconds"] == timeout
    assert observed["policy_origin"] == ("explicit" if timeout is not None else "absent")
    store = Store(tmp_path / "home/state.db")
    before = (store.list_events(solved["run_id"]), store.list_artifacts(solved["run_id"]))
    assert cli.main([
        "status", solved["run_id"], "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["solve_execution"] == observed
    assert (store.list_events(solved["run_id"]), store.list_artifacts(solved["run_id"])) == before


def test_answer_starts_a_new_active_execution_with_the_same_policy(tmp_path, monkeypatch, capsys):
    from test_conversational_automatic_bundle import automatic_setup

    _runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    args.extend(["--solve-wall-timeout", "300"])
    assert cli.main(args) == 0
    waiting = json.loads(capsys.readouterr().out)
    first = waiting["solve_execution"]
    assert first["state"] == "awaiting_input"
    assert first["stopping_reason"] == "awaiting_input"
    store = Store(tmp_path / "home/state.db")
    assert not any(task.orchestration for task in store.list_tasks(waiting["run_id"]))
    assert cli.main([
        "answer", waiting["run_id"], "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    answered = json.loads(capsys.readouterr().out)
    second = answered["solve_execution"]
    assert second["execution_id"] != first["execution_id"]
    assert second["policy_seconds"] == first["policy_seconds"] == 300.0
    assert second["policy_origin"] == first["policy_origin"] == "explicit"
    assert second["state"] == "terminal" and second["stopping_reason"] == "completed"
    assert len([task for task in store.list_tasks(waiting["run_id"]) if task.orchestration]) == 1


def test_cancel_first_preserves_cancelled_store_winner(tmp_path):
    store, run, task, attempt, observation = _observed_run(tmp_path)
    assert store.cancel_run(run.id)
    assert not store.fail_budget(run.id, "solve_wall_timeout", 31.0, 30.0, "private exception detail")
    assert not store.finish_task(task.id, attempt.id, True)
    observation.observe("delivery", state="terminal", reason="solve_wall_timeout")
    current = store.settle_run(run.id)
    assert current.status == RunStatus.CANCELLED
    assert store.get_task(task.id).state == TaskStatus.CANCELLED
    assert solve_execution_status(store, current)["stopping_reason"] == "cancelled"
    assert not any(event["type"] == "budget_exceeded" for event in store.list_events(run.id))


def test_budget_first_preserves_failed_orchestration_and_one_budget_event(tmp_path):
    store, run, task, attempt, observation = _observed_run(tmp_path)
    assert store.fail_budget(run.id, "solve_wall_timeout", 31.0, 30.0, "private exception detail")
    assert not store.cancel_run(run.id)
    assert not store.fail_budget(run.id, "solve_wall_timeout", 99.0, 30.0, "different private detail")
    assert not store.finish_task(task.id, attempt.id, True)
    observation.observe("candidate_generation", state="terminal", reason="cancelled")
    current = store.settle_run(run.id)
    assert current.status == RunStatus.FAILED
    assert store.get_task(task.id).state == TaskStatus.FAILED
    projected = solve_execution_status(store, current)
    assert set(projected) == FIELDS
    assert projected["state"] == "terminal"
    assert projected["stopping_reason"] == "solve_wall_timeout"
    assert "private" not in json.dumps(projected)
    assert len([event for event in store.list_events(run.id) if event["type"] == "budget_exceeded"]) == 1


def test_status_drops_internal_clock_and_arbitrary_exception_fields(tmp_path):
    store, run, _task, _attempt, _observation = _observed_run(tmp_path)
    payload = solve_execution_status(store, run)
    store.append_event(run.id, "solve_execution", {
        **payload, "deadline": 1234.5, "remaining_seconds": 17.0,
        "exception": "SECRET/provider response and path", "provider_status": "running",
    })
    before = store.list_events(run.id)
    projected = solve_execution_status(store, run)
    assert projected == payload
    assert set(projected) == FIELDS
    assert store.list_events(run.id) == before
    assert "SECRET" not in json.dumps(projected)


@pytest.mark.parametrize("field,value", [
    ("stage", "private/exception/path"), ("stopping_reason", "unbounded secret text"),
    ("state", "invented"), ("policy_seconds", 99.0), ("execution_id", "provider-job-secret"),
])
def test_malformed_latest_observation_is_not_projected(tmp_path, field, value):
    store, run, _task, _attempt, _observation = _observed_run(tmp_path)
    payload = solve_execution_status(store, run)
    store.append_event(run.id, "solve_execution", {**payload, field: value})
    assert solve_execution_status(store, run) is None


def test_incomplete_latest_observation_is_not_projected(tmp_path):
    store, run, _task, _attempt, _observation = _observed_run(tmp_path)
    payload = solve_execution_status(store, run)
    payload.pop("stopping_reason")
    store.append_event(run.id, "solve_execution", payload)
    assert solve_execution_status(store, run) is None


def test_failed_orchestration_has_bounded_terminal_status(tmp_path):
    store, run, task, attempt, observation = _observed_run(tmp_path)
    assert store.finish_task(task.id, attempt.id, False, error="arbitrary private exception")
    current = store.settle_run(run.id)
    observation.observe("delivery", state="terminal", reason="failed")
    projected = solve_execution_status(store, current)
    assert current.status == RunStatus.FAILED
    assert store.get_task(task.id).state == TaskStatus.FAILED
    assert projected["state"] == "terminal"
    assert projected["stopping_reason"] == "failed"
    assert "arbitrary private exception" not in json.dumps(projected)
