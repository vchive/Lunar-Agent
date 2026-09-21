"""Dependency waits cannot masquerade as questions or bypass scheduler prerequisites."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lunar_evolution.models import RunStatus, TaskStatus
from lunar_evolution.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    result = Store(tmp_path / "state.db")
    result.initialize()
    return result


def dependency_run(store):
    return store.create_run("wait for verified input", tasks=[
        {"id": "z-producer", "title": "Produce", "prompt": "produce"},
        {"id": "a-dependent", "title": "Consume", "prompt": "consume", "depends_on": ["z-producer"]},
    ])


def persisted_question(store, task_id, question):
    # Exercise legacy persisted rows without changing the schema or invoking await_input's
    # validation, which correctly refuses new blank questions.
    with sqlite3.connect(store.database) as connection:
        connection.execute("UPDATE tasks SET input_question = ? WHERE id = ?", (question, task_id))


@pytest.mark.parametrize("question", [None, "", " ", "\t\r\n", "\u2003\u00a0"])
def test_dependency_wait_never_accepts_stray_answer_and_releases_only_after_success(store, question):
    run = dependency_run(store)
    persisted_question(store, "a-dependent", question)
    events = store.list_events(run.id)
    assert store.pending_input(run.id) is None
    assert store.answer_input(run.id, "tasks/misleading-answer.json") is None
    assert store.get_task("a-dependent").state == TaskStatus.WAITING
    assert store.get_task("a-dependent").input_answer_path is None
    assert store.list_events(run.id) == events
    assert store.settle_run(run.id).status == RunStatus.RUNNING

    producer = store.next_task(run.id)
    assert producer.id == "z-producer"
    attempt = store.claim_task(producer.id, "fixture")
    assert store.next_task(run.id) is None
    assert store.claim_task("a-dependent", "fixture") is None
    assert store.pending_input(run.id) is None
    assert store.finish_task(producer.id, attempt.id, True)
    assert store.next_task(run.id).id == "a-dependent"
    dependent_attempt = store.claim_task("a-dependent", "fixture")
    assert store.finish_task("a-dependent", dependent_attempt.id, True)
    assert store.settle_run(run.id).status == RunStatus.SUCCEEDED


def test_real_question_selected_after_earlier_dependency_wait_and_keeps_dependency_gated(store):
    run = dependency_run(store)
    producer = store.next_task(run.id)
    attempt = store.claim_task(producer.id, "fixture")
    assert store.await_input(producer.id, attempt.id, "tasks/request.json", "Choose format", ["csv", "json"])
    pending = store.pending_input(run.id)
    assert pending["task_id"] == "z-producer"
    assert pending["question"] == "Choose format"
    assert pending["options"] == ["csv", "json"]
    assert store.next_task(run.id) is None
    assert store.settle_run(run.id).status == RunStatus.AWAITING_INPUT
    assert store.answer_input(run.id, "tasks/real-answer.json") == "z-producer"
    assert store.pending_input(run.id) is None
    assert store.answer_input(run.id, "tasks/second-misleading-answer.json") is None
    assert store.get_task("a-dependent").state == TaskStatus.WAITING
    assert store.get_task("a-dependent").input_answer_path is None
    assert store.next_task(run.id).id == "z-producer"
    resumed = store.claim_task("z-producer", "fixture")
    assert store.finish_task("z-producer", resumed.id, True)
    assert store.next_task(run.id).id == "a-dependent"
    answered = [event for event in store.list_events(run.id) if event["type"] == "input_answered"]
    assert len(answered) == 1 and answered[0]["task_id"] == "z-producer"


@pytest.mark.parametrize("question", ["", " \n\t", "\u2003"])
def test_legacy_blank_question_without_dependencies_is_scheduler_ready(store, question):
    run = store.create_run("legacy blank question")
    task = store.next_task(run.id)
    attempt = store.claim_task(task.id, "fixture")
    assert store.await_input(task.id, attempt.id, "request.json", "Original question")
    persisted_question(store, task.id, question)
    assert store.get_run(run.id).status == RunStatus.AWAITING_INPUT
    assert store.pending_input(run.id) is None
    assert store.answer_input(run.id, "stray-answer.json") is None
    assert store.settle_run(run.id).status == RunStatus.RUNNING
    assert store.next_task(run.id).id == task.id
    assert store.get_task(task.id).state == TaskStatus.READY


def test_existing_nonempty_question_still_pauses_and_preserves_question_bytes(store):
    run = store.create_run("legacy real question")
    task = store.next_task(run.id)
    attempt = store.claim_task(task.id, "fixture")
    question = " \tWhich format?\n "
    assert store.await_input(task.id, attempt.id, "request.json", question)
    assert store.pending_input(run.id)["question"] == question
    assert store.next_task(run.id) is None
    assert store.settle_run(run.id).status == RunStatus.AWAITING_INPUT
    assert store.answer_input(run.id, "answer.json") == task.id
    assert store.next_task(run.id).id == task.id


def test_failed_dependency_blocks_wait_without_inventing_input_request(store):
    run = dependency_run(store)
    task = store.next_task(run.id)
    attempt = store.claim_task(task.id, "fixture")
    assert store.finish_task(task.id, attempt.id, False, error="fixture failure")
    assert store.next_task(run.id) is None
    assert store.get_task("a-dependent").state == TaskStatus.BLOCKED
    assert store.settle_run(run.id).status == RunStatus.FAILED
    assert store.pending_input(run.id) is None
    assert store.answer_input(run.id, "stray-answer.json") is None


def test_cancellation_preserves_terminal_state_and_never_releases_question_or_dependency(store):
    run = dependency_run(store)
    task = store.next_task(run.id)
    attempt = store.claim_task(task.id, "fixture")
    assert store.await_input(task.id, attempt.id, "request.json", "Proceed?")
    assert store.cancel_run(run.id)
    assert store.pending_input(run.id) is None
    assert store.answer_input(run.id, "late-answer.json") is None
    assert store.next_task(run.id) is None
    assert store.settle_run(run.id).status == RunStatus.CANCELLED
    assert all(task.state == TaskStatus.CANCELLED for task in store.list_tasks(run.id))


def test_real_question_replacement_does_not_accept_answer_for_stale_row(store, monkeypatch):
    run = store.create_run("concurrent replacement")
    task = store.next_task(run.id)
    attempt = store.claim_task(task.id, "fixture")
    assert store.await_input(task.id, attempt.id, "request.json", "Original question")
    original = store._pending_input_row

    def replaced(connection, run_id):
        row = original(connection, run_id)
        connection.execute("UPDATE tasks SET input_question = NULL WHERE id = ?", (task.id,))
        return row

    monkeypatch.setattr(store, "_pending_input_row", replaced)
    assert store.answer_input(run.id, "stale-answer.json") is None
    assert store.get_task(task.id).state == TaskStatus.WAITING
    assert store.get_task(task.id).input_answer_path is None
    assert not any(event["type"] == "input_answered" for event in store.list_events(run.id))
