from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution.models import RunStatus, TaskStatus
from lunar_evolution.store import Store


def test_orchestration_task_is_durable_and_hidden_from_scheduler(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run(
        "automatic solve",
        tmp_path / "run",
        tasks=[{"id": "intake", "title": "intake", "prompt": "intake"}],
    )
    intake = store.next_task(run.id)
    assert intake is not None
    attempt = store.claim_task(intake.id, "compiler")
    assert attempt is not None
    assert store.finish_task(intake.id, attempt.id, True)

    orchestration = store.ensure_orchestration_task(
        run.id, title="Automatic solve orchestration", prompt="evolve and deliver"
    )
    assert orchestration.orchestration is True
    assert store.next_task(run.id) is None
    assert store.claim_task(orchestration.id, "ordinary-worker") is None
    assert store.ensure_orchestration_task(
        run.id, title="different title", prompt="different prompt"
    ).id == orchestration.id

    orchestration_attempt = store.claim_orchestration_task(orchestration.id, "automatic-solve")
    assert orchestration_attempt is not None
    assert store.next_task(run.id) is None
    running = store.settle_run(run.id)
    assert running is not None
    assert running.status == RunStatus.RUNNING

    assert store.finish_task(orchestration.id, orchestration_attempt.id, True)
    settled = store.settle_run(run.id)
    assert settled is not None
    assert settled.status == RunStatus.SUCCEEDED


def test_orchestration_claim_is_idempotent_for_an_active_attempt(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("automatic solve", tmp_path / "run")
    task = store.ensure_orchestration_task(
        run.id, title="Automatic solve orchestration", prompt="evolve and deliver"
    )
    first = store.claim_orchestration_task(task.id, "automatic-solve")
    assert first is not None
    second = store.claim_orchestration_task(task.id, "automatic-solve")
    assert second is not None
    assert second.id == first.id
    assert store.get_task(task.id).state == TaskStatus.RUNNING  # type: ignore[union-attr]


def test_terminal_parent_cannot_gain_new_orchestration(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("terminal")
    assert store.cancel_run(run.id)
    with pytest.raises(ValueError, match="terminal run"):
        store.ensure_orchestration_task(run.id, title="orchestration", prompt="continue")


def test_automatic_parent_remains_running_through_delivery(tmp_path, monkeypatch, capsys):
    from test_conversational_automatic_bundle import automatic_setup

    from lunar_evolution import cli
    from lunar_evolution.controller import LocalController

    _runtime, args = automatic_setup(tmp_path, monkeypatch)
    original = LocalController.deliver_bundle_to_parent
    observed = []

    def deliver(controller, parent_id, child_id, contract, result, **kwargs):
        parent = controller.store.get_run(parent_id)
        tasks = [task for task in controller.store.list_tasks(parent_id) if task.orchestration]
        assert parent is not None and parent.status == RunStatus.RUNNING
        assert len(tasks) == 1 and tasks[0].state == TaskStatus.RUNNING
        assert controller.store.next_task(parent_id) is None
        observed.append(tasks[0].id)
        return original(controller, parent_id, child_id, contract, result, **kwargs)

    monkeypatch.setattr(LocalController, "deliver_bundle_to_parent", deliver)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    assert payload["status"] == "succeeded"
    assert len(observed) == 1
    assert store.get_task(observed[0]).state == TaskStatus.SUCCEEDED
    before = store.list_events(payload["run_id"])
    assert cli.main([
        "resume", payload["run_id"], "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    capsys.readouterr()
    assert store.list_events(payload["run_id"]) == before
    assert len(observed) == 1


def test_failed_child_never_finishes_parent_successfully(tmp_path, monkeypatch, capsys):
    from dataclasses import replace

    from test_conversational_automatic_bundle import automatic_setup

    from lunar_evolution import cli
    from lunar_evolution.controller import LocalController

    _runtime, args = automatic_setup(tmp_path, monkeypatch)
    original = LocalController.run_evolution

    def failed(controller, *arguments, **kwargs):
        child, result = original(controller, *arguments, **kwargs)
        with controller.store._connect() as connection:
            connection.execute("UPDATE runs SET status = 'failed' WHERE id = ?", (child.id,))
        return replace(child, status=RunStatus.FAILED), result

    monkeypatch.setattr(LocalController, "run_evolution", failed)
    assert cli.main(args) == 1
    payload = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    parent = store.get_run(payload["run_id"])
    assert parent is not None and parent.status == RunStatus.FAILED
    tasks = [task for task in store.list_tasks(parent.id) if task.orchestration]
    assert len(tasks) == 1 and tasks[0].state == TaskStatus.FAILED
    assert not any(event["type"] == "run_succeeded" for event in store.list_events(parent.id))


def test_legacy_automatic_request_does_not_gain_orchestration(tmp_path, monkeypatch, capsys):
    from test_conversational_automatic_bundle import automatic_setup

    from lunar_evolution import cli

    _runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    request = next(event for event in store.list_events(initial["run_id"])
                   if event["type"] == "evolution_requested")
    request["payload"].pop("automatic_lifecycle_version")
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?",
                           (json.dumps(request["payload"]), request["id"]))
    assert cli.main([
        "answer", initial["run_id"], "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["status"] == "succeeded"
    assert not any(task.orchestration for task in store.list_tasks(initial["run_id"]))
