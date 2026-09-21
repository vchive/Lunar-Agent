"""Native automatic solve deadline fixtures never contact a model provider."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_conversational_automatic_bundle import automatic_setup

from lunar_evolution import bundle_parent_delivery, candidate_evaluation, cli
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.store import Store


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def setup_deadline(tmp_path, monkeypatch, *, seconds=10, clarify=False):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=clarify)
    clock = Clock()
    controls = []

    def control(*args, **kwargs):
        kwargs["clock"] = clock
        result = SolveExecutionControl(*args, **kwargs)
        controls.append(result)
        return result

    monkeypatch.setattr(cli, "SolveExecutionControl", control)
    args.extend(["--solve-wall-timeout", str(seconds)])
    return runtime, args, clock, controls


def stage_of(prompt):
    if "contract compiler" in prompt:
        return "contract"
    if "frozen local evaluator bundle" in prompt:
        return "compiler"
    if "adversarial evaluator auditor" in prompt:
        return "auditor"
    return "generation"


def parent_state(tmp_path):
    store = Store(tmp_path / "home/state.db")
    parent = store.get_run_by_workspace(tmp_path / "conversation")
    assert parent is not None
    return store, parent


def assert_exhausted(tmp_path):
    store, parent = parent_state(tmp_path)
    assert parent.status.value == "failed"
    events = store.list_events(parent.id)
    failures = [event for event in events if event["type"] == "budget_exceeded"]
    assert len(failures) == 1
    assert failures[0]["payload"]["limit"] == "solve_wall_timeout"
    assert not any(event["type"] == "bundle_candidate_delivered" for event in events)
    assert not (parent.workspace / "output/result.json").exists()
    return store, parent


@pytest.mark.parametrize("expired_stage, expected_calls", [
    ("contract", (1, 0, 0, 0)),
    ("compiler", (1, 1, 0, 0)),
    ("auditor", (1, 1, 1, 0)),
    ("generation", (1, 1, 1, 1)),
])
def test_late_runtime_result_exhausts_parent_once_before_next_stage(
    tmp_path, monkeypatch, capsys, expired_stage, expected_calls,
):
    runtime, args, clock, _ = setup_deadline(tmp_path, monkeypatch)
    original = runtime.run

    def run(prompt, workspace, timeout=None, **kwargs):
        result = original(prompt, workspace, timeout, **kwargs)
        if stage_of(prompt) == expired_stage:
            clock.value = 110.0
        return result

    monkeypatch.setattr(runtime, "run", run)
    assert cli.main(args) != 0
    capsys.readouterr()
    assert_exhausted(tmp_path)
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls,
            runtime.generator_calls) == expected_calls


@pytest.mark.parametrize("command", ["solve", "resume"])
def test_exhausted_parent_continuation_cannot_start_another_generation(
    tmp_path, monkeypatch, capsys, command,
):
    runtime, args, clock, _ = setup_deadline(tmp_path, monkeypatch)
    original = runtime.run

    def run(prompt, workspace, timeout=None, **kwargs):
        result = original(prompt, workspace, timeout, **kwargs)
        if stage_of(prompt) == "generation":
            clock.value = 110.0
        return result

    monkeypatch.setattr(runtime, "run", run)
    assert cli.main(args) != 0
    capsys.readouterr()
    store, parent = assert_exhausted(tmp_path)
    events = store.list_events(parent.id)
    snapshots = {path.relative_to(parent.workspace): path.read_bytes()
                 for path in parent.workspace.rglob("*") if path.is_file()}
    clock.value = 1000.0
    monkeypatch.setattr(runtime, "run", lambda *a, **kw: pytest.fail("terminal solve restarted runtime"))
    followup = (["solve", "--resume", "--run-id", parent.id]
                if command == "solve" else ["resume", parent.id])
    assert cli.main([*followup, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"]) != 0
    capsys.readouterr()
    assert store.list_events(parent.id) == events
    assert {path.relative_to(parent.workspace): path.read_bytes()
            for path in parent.workspace.rglob("*") if path.is_file()} == snapshots
    assert_exhausted(tmp_path)


def test_delivery_checks_deadline_after_material_reads_before_publication(
    tmp_path, monkeypatch, capsys,
):
    _, args, clock, _ = setup_deadline(tmp_path, monkeypatch)
    original = bundle_parent_delivery._outputs
    observed = []

    def outputs(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(True)
        clock.value = 110.0
        return result

    monkeypatch.setattr(bundle_parent_delivery, "_outputs", outputs)
    assert cli.main(args) != 0
    capsys.readouterr()
    assert observed
    assert_exhausted(tmp_path)


@pytest.mark.parametrize("boundary", ["candidate_execution", "scoring"])
def test_late_local_process_result_cannot_admit_more_work(
    tmp_path, monkeypatch, capsys, boundary,
):
    from lunar_evolution import candidate_execution_runner

    runtime, args, clock, _ = setup_deadline(tmp_path, monkeypatch)
    module, name = ((candidate_execution_runner, "_bounded_process")
                    if boundary == "candidate_execution"
                    else (candidate_evaluation, "_bounded_process_bytes"))
    original = getattr(module, name)
    calls = []

    def process(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        clock.value = 110.0
        return result

    monkeypatch.setattr(module, name, process)
    assert cli.main(args) != 0
    capsys.readouterr()
    assert calls == [True]
    assert runtime.generator_calls == 1
    assert_exhausted(tmp_path)


def test_scoring_receives_remaining_time_without_rewriting_frozen_authority(
    tmp_path, monkeypatch, capsys,
):
    from lunar_evolution import candidate_execution_runner

    runtime, args, clock, controls = setup_deadline(tmp_path, monkeypatch, seconds=6)
    original_runtime = runtime.run
    original_candidate = candidate_execution_runner._bounded_process
    original_evaluator = candidate_evaluation._bounded_process_bytes
    frozen = {}
    generation_timeouts = []
    candidate_timeouts = []
    evaluator_timeouts = []

    def run(prompt, workspace, timeout=None, **kwargs):
        stage = stage_of(prompt)
        if stage == "generation":
            generation_timeouts.append((clock.value, timeout))
            if not frozen:
                parent = tmp_path / "conversation"
                paths = [parent / "bundle-profile.json", parent / "solve/contract.json",
                         parent / "data/raw/value", *sorted((parent / "evaluator-bundle").rglob("*"))]
                frozen.update({path: path.read_bytes() for path in paths if path.is_file()})
        result = original_runtime(prompt, workspace, timeout, **kwargs)
        if stage in {"contract", "compiler", "auditor"}:
            clock.value += 1.0
        elif len(generation_timeouts) == 1:
            clock.value += 0.5
        return result

    def candidate(*args, **kwargs):
        candidate_timeouts.append((clock.value, kwargs["timeout"]))
        result = original_candidate(*args, **kwargs)
        if len(candidate_timeouts) == 1:
            clock.value += 0.5
        return result

    def evaluator(*args, **kwargs):
        evaluator_timeouts.append((clock.value, kwargs["timeout"]))
        return original_evaluator(*args, **kwargs)

    monkeypatch.setattr(runtime, "run", run)
    monkeypatch.setattr(candidate_execution_runner, "_bounded_process", candidate)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", evaluator)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert len(controls) == 1
    assert controls[0].started_at == 100.0
    assert controls[0].deadline == 106.0
    for timeouts in (generation_timeouts, candidate_timeouts, evaluator_timeouts):
        assert len(timeouts) == 4
        assert all(timeout == min(3.0, 106.0 - admitted_at) for admitted_at, timeout in timeouts)
    assert frozen and all(path.read_bytes() == content for path, content in frozen.items())
    plans = list((Path(payload["workspace"]) / "evolution-run").rglob("plan.json"))
    assert len(plans) == 4
    for path in plans:
        assert json.loads(path.read_text())["timeout_seconds"] == 3.0


def test_answer_starts_one_fresh_execution_after_unbounded_human_wait(
    tmp_path, monkeypatch, capsys,
):
    from test_preparation_recovery_cli import snapshot

    runtime, args, clock, controls = setup_deadline(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    assert initial["status"] == "awaiting_input"
    assert initial["solve_execution"]["state"] == "awaiting_input"
    store, parent = parent_state(tmp_path)
    before = snapshot(store, parent.id, parent.workspace)
    clock.value = 1000.0
    for _ in range(2):
        assert cli.main(["status", parent.id, "--home", str(tmp_path / "home"), "--json"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["solve_execution"] == initial["solve_execution"]
    assert snapshot(store, parent.id, parent.workspace) == before
    assert len(controls) == 1
    assert cli.main([
        "answer", parent.id, "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    final = json.loads(capsys.readouterr().out)
    assert final["status"] == "succeeded"
    assert [(control.started_at, control.deadline) for control in controls] == [
        (100.0, 110.0), (1000.0, 1010.0),
    ]
    assert final["solve_execution"]["execution_id"] != initial["solve_execution"]["execution_id"]
    assert final["solve_execution"]["policy_seconds"] == 10.0
    assert final["solve_execution"]["state"] == "terminal"
    assert (runtime.contract_calls, runtime.generator_calls) == (2, 4)


def test_malformed_execution_observation_does_not_break_read_only_status(
    tmp_path, monkeypatch, capsys,
):
    from test_preparation_recovery_cli import snapshot

    _, args, _, _ = setup_deadline(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    capsys.readouterr()
    store, parent = parent_state(tmp_path)
    event = [event for event in store.list_events(parent.id) if event["type"] == "solve_execution"][-1]
    malformed = dict(event["payload"])
    del malformed["stopping_reason"]
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(malformed), event["id"]))
    before = snapshot(store, parent.id, parent.workspace)
    assert cli.main(["status", parent.id, "--home", str(tmp_path / "home"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_input"
    assert "solve_execution" not in payload
    assert snapshot(store, parent.id, parent.workspace) == before


def test_busy_automatic_owner_rejects_answer_before_consuming_input(
    tmp_path, monkeypatch, capsys,
):
    from test_preparation_recovery_cli import snapshot

    from lunar_evolution.automatic_solve_lifecycle import own_automatic_solve

    runtime, args, _, _ = setup_deadline(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    capsys.readouterr()
    store, parent = parent_state(tmp_path)
    before, pending = snapshot(store, parent.id, parent.workspace), store.pending_input(parent.id)
    with own_automatic_solve(parent.id, parent.workspace):
        assert cli.main([
            "answer", parent.id, "maximize value", "--runtime", "mock",
            "--home", str(tmp_path / "home"), "--json",
        ]) == 2
    assert "active execution owner" in json.loads(capsys.readouterr().err)["error"]
    assert snapshot(store, parent.id, parent.workspace) == before
    assert store.pending_input(parent.id) == pending
    assert (runtime.contract_calls, runtime.generator_calls) == (1, 0)


@pytest.mark.parametrize("winner", ["cancelled", "budget"])
def test_recorded_terminal_winner_survives_late_runtime_and_budget_check(
    tmp_path, monkeypatch, capsys, winner,
):
    runtime, args, clock, _ = setup_deadline(tmp_path, monkeypatch)
    original = runtime.run

    def run(prompt, workspace, timeout=None, **kwargs):
        result = original(prompt, workspace, timeout, **kwargs)
        if stage_of(prompt) == "generation":
            store, parent = parent_state(tmp_path)
            if winner == "cancelled":
                assert store.cancel_run(parent.id)
            else:
                assert store.fail_budget(parent.id, "solve_wall_timeout", 10.0, 10.0, "solve deadline reached")
                assert not store.cancel_run(parent.id)
            clock.value = 110.0
        return result

    monkeypatch.setattr(runtime, "run", run)
    assert cli.main(args) != 0
    payload = json.loads(capsys.readouterr().out)
    store, parent = parent_state(tmp_path)
    assert parent.status.value == ("cancelled" if winner == "cancelled" else "failed")
    assert payload["solve_execution"]["state"] == "terminal"
    assert payload["solve_execution"]["stopping_reason"] == (
        "cancelled" if winner == "cancelled" else "solve_wall_timeout"
    )
    events = store.list_events(parent.id)
    assert sum(event["type"] == "budget_exceeded" for event in events) == (winner == "budget")
    assert not any(event["type"] == "bundle_candidate_delivered" for event in events)
    assert runtime.generator_calls == 1


@pytest.mark.parametrize("boundary", ["generation", "candidate_execution", "scoring"])
def test_cancellation_without_wall_timeout_blocks_later_execution_and_delivery(
    tmp_path, monkeypatch, capsys, boundary,
):
    from lunar_evolution import candidate_execution_runner

    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original_runtime = runtime.run
    original_candidate = candidate_execution_runner._bounded_process
    original_evaluator = candidate_evaluation._bounded_process_bytes
    candidate_calls = []
    evaluator_calls = []

    def cancel_parent():
        store, parent = parent_state(tmp_path)
        assert store.cancel_run(parent.id)

    def run(prompt, workspace, timeout=None, **kwargs):
        result = original_runtime(prompt, workspace, timeout, **kwargs)
        if boundary == "generation" and stage_of(prompt) == "generation":
            cancel_parent()
        return result

    def candidate(*args, **kwargs):
        candidate_calls.append(True)
        result = original_candidate(*args, **kwargs)
        if boundary == "candidate_execution":
            cancel_parent()
        return result

    def evaluator(*args, **kwargs):
        evaluator_calls.append(True)
        result = original_evaluator(*args, **kwargs)
        if boundary == "scoring":
            cancel_parent()
        return result

    monkeypatch.setattr(runtime, "run", run)
    monkeypatch.setattr(candidate_execution_runner, "_bounded_process", candidate)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", evaluator)

    assert cli.main(args) != 0
    capsys.readouterr()

    store, parent = parent_state(tmp_path)
    assert parent.status.value == "cancelled"
    assert runtime.generator_calls == 1
    assert len(candidate_calls) == (0 if boundary == "generation" else 1)
    assert len(evaluator_calls) == (1 if boundary == "scoring" else 0)
    assert not any(event["type"] == "bundle_candidate_delivered" for event in store.list_events(parent.id))
    assert not (parent.workspace / "output/result.json").exists()
