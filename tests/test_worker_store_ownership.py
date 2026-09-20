"""Durable worker ownership must remain exact across restart and cancellation races."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from famou.models import WorkerOutcome, WorkerPhase, WorkerProcess
from famou.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    value = Store(tmp_path / "state.db")
    value.initialize()
    return value


def _start(store: Store, owner: str = "caller", service: str | None = "service-a"):
    worker = store.create_worker(owner, "worker", "owned work")
    attempt = store.start_worker_attempt(worker.id, owner, "execute", service_owner_id=service)
    return worker, attempt


def test_worker_owner_migration_preserves_legacy_attempts(store: Store) -> None:
    worker, attempt = _start(store, service=None)
    with sqlite3.connect(store.database) as connection:
        connection.execute("DROP INDEX worker_attempts_owner_idx")
        connection.execute("DROP TABLE worker_attempt_processes")
        connection.execute("ALTER TABLE worker_attempts DROP COLUMN service_owner_id")
        connection.execute("DELETE FROM schema_migrations WHERE version = 8")

    reopened = Store(store.database)
    reopened.initialize()
    reopened.initialize()

    assert reopened.get_worker_attempt(worker.id, attempt.id) == attempt
    assert reopened.list_worker_owned_attempts("caller") == []
    assert reopened.reconcile_workers() == 0
    assert reopened.reconcile_workers(
        owner_id="caller", service_owner_id="invented-owner", worker_id=worker.id, attempt_id=attempt.id,
    ) == 0
    assert reopened.get_worker(worker.id).phase is WorkerPhase.RUNNING
    with sqlite3.connect(store.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 8").fetchone()[0] == 1


def test_worker_claim_serializes_independent_services(store: Store) -> None:
    worker = store.create_worker("caller", "worker", "one execution")
    barrier = threading.Barrier(2)

    def claim(service_owner_id: str):
        independent_store = Store(store.database)
        barrier.wait(timeout=3)
        try:
            return independent_store.start_worker_attempt(
                worker.id, "caller", "execute", service_owner_id=service_owner_id,
            )
        except ValueError as exc:
            assert str(exc) == "worker is already running"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ("service-a", "service-b")))
    attempts = store.list_worker_attempts(worker.id)
    assert len(attempts) == 1
    assert sum(claim is not None for claim in claims) == 1
    assert attempts[0].service_owner_id in {"service-a", "service-b"}


@pytest.mark.parametrize("service_owner_id", ["", " ", "x" * 129, False, 123])
def test_worker_claim_rejects_invalid_service_identity(store: Store, service_owner_id) -> None:
    worker = store.create_worker("caller", "worker", "owned work")
    with pytest.raises(ValueError, match="service owner"):
        store.start_worker_attempt(worker.id, "caller", "work", service_owner_id=service_owner_id)
    assert store.get_worker(worker.id).phase is WorkerPhase.IDLE
    assert store.list_worker_attempts(worker.id) == []


def test_worker_attempt_lookup_and_candidates_are_scoped(store: Store) -> None:
    first, attempt = _start(store)
    other, other_attempt = _start(store, owner="other", service="service-b")
    _start(store, service=None)
    assert store.get_worker_attempt(
        first.id, attempt.id, owner_id="caller", service_owner_id="service-a",
    ) == attempt
    assert store.get_worker_attempt(first.id, attempt.id, owner_id="other") is None
    assert store.get_worker_attempt(first.id, attempt.id, service_owner_id="service-b") is None
    assert store.get_worker_attempt(first.id, other_attempt.id) is None
    assert store.get_worker_attempt(other.id, attempt.id) is None
    assert store.list_worker_owned_attempts("caller") == [attempt]
    assert store.list_worker_owned_attempts("other") == [other_attempt]
    assert store.list_worker_owned_attempts("unknown") == []


def test_worker_processes_preserve_multiple_groups_and_exact_identity(store: Store) -> None:
    worker, attempt = _start(store)
    other, other_attempt = _start(store, service="service-b")
    assert not store.register_worker_process(worker.id, other_attempt.id, "service-a", 101, 101)
    assert not store.register_worker_process(worker.id, attempt.id, "service-b", 101, 101)
    assert store.register_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert store.register_worker_process(worker.id, attempt.id, "service-a", 202, 202)
    assert store.register_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert store.register_worker_process(other.id, other_attempt.id, "service-b", 303, 303)
    assert store.list_worker_processes(worker.id, attempt.id, "service-a") == [
        WorkerProcess(worker.id, attempt.id, "service-a", 101, 101),
        WorkerProcess(worker.id, attempt.id, "service-a", 202, 202),
    ]
    assert store.list_worker_processes(worker.id, attempt.id, "service-b") == []
    assert not store.clear_worker_process(worker.id, attempt.id, "service-b", 101, 101)
    assert not store.clear_worker_process(other.id, attempt.id, "service-a", 101, 101)
    assert not store.clear_worker_process(worker.id, attempt.id, "service-a", 101, 202)
    assert store.clear_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert not store.clear_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert [item.pid for item in store.list_worker_processes(worker.id, attempt.id, "service-a")] == [202]
    assert [item.pid for item in store.list_worker_processes(other.id, other_attempt.id, "service-b")] == [303]


@pytest.mark.parametrize("pid,pgid", [(True, 9), (9, False), (0, 9), (9, 1), (9.0, 9), (9, None)])
def test_worker_process_registration_rejects_non_group_identity(store: Store, pid, pgid) -> None:
    worker, attempt = _start(store)
    with pytest.raises(ValueError, match="process identifiers"):
        store.register_worker_process(worker.id, attempt.id, "service-a", pid, pgid)
    assert store.list_worker_processes(worker.id, attempt.id, "service-a") == []


def test_cancelled_attempt_retains_late_process_and_blocks_resume_until_cleanup(store: Store) -> None:
    worker, attempt = _start(store)
    store.cancel_worker_tree(worker.id, "caller")
    assert store.register_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    candidate = store.list_worker_owned_attempts("caller")
    assert len(candidate) == 1 and candidate[0].status == "finished"
    assert candidate[0].outcome is WorkerOutcome.STOPPED
    reopened = Store(store.database)
    reopened.initialize()
    assert reopened.list_worker_processes(worker.id, attempt.id, "service-a") == [
        WorkerProcess(worker.id, attempt.id, "service-a", 101, 101),
    ]
    with pytest.raises(ValueError, match="retained process ownership"):
        reopened.start_worker_attempt(worker.id, "caller", "resume", service_owner_id="service-b")
    assert reopened.clear_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert reopened.list_worker_owned_attempts("caller") == []
    resumed = reopened.start_worker_attempt(worker.id, "caller", "resume", service_owner_id="service-b")
    assert not reopened.clear_worker_process(worker.id, resumed.id, "service-a", 101, 101)
    assert reopened.reconcile_workers(
        owner_id="caller", service_owner_id="service-a", worker_id=worker.id, attempt_id=attempt.id,
    ) == 0
    assert reopened.get_worker(worker.id).phase is WorkerPhase.RUNNING
    assert reopened.get_worker_attempt(worker.id, resumed.id).status == "running"


def test_reconcile_requires_exact_scope_and_preserves_unrelated_attempts(store: Store) -> None:
    worker, attempt = _start(store)
    sibling, sibling_attempt = _start(store, service="service-a")
    other, other_attempt = _start(store, owner="other", service="service-b")
    scope = {"owner_id": "caller", "service_owner_id": "service-a", "worker_id": worker.id, "attempt_id": attempt.id}
    assert store.reconcile_workers() == 0
    for key in scope:
        assert store.reconcile_workers(**{**scope, key: None}) == 0
        assert store.reconcile_workers(**{**scope, key: "wrong"}) == 0
    assert store.register_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert store.reconcile_workers(**scope) == 0
    assert store.get_worker(worker.id).phase is WorkerPhase.RUNNING
    assert store.clear_worker_process(worker.id, attempt.id, "service-a", 101, 101)
    assert store.reconcile_workers(**scope) == 1
    recovered = store.get_worker(worker.id)
    assert recovered.phase is WorkerPhase.IDLE
    assert recovered.outcome is WorkerOutcome.LOST
    assert store.get_worker_attempt(worker.id, attempt.id).outcome is WorkerOutcome.LOST
    assert store.reconcile_workers(**scope) == 0
    assert store.get_worker_attempt(sibling.id, sibling_attempt.id).status == "running"
    assert store.get_worker_attempt(other.id, other_attempt.id).status == "running"
    assert len([event for event in store.list_worker_events(worker.id) if event["type"] == "worker_lost"]) == 1


def test_stale_reconcile_cannot_overwrite_new_attempt_or_first_terminal_result(store: Store) -> None:
    worker, attempt = _start(store)
    scope = {"owner_id": "caller", "service_owner_id": "service-a", "worker_id": worker.id, "attempt_id": attempt.id}
    assert store.settle_worker(worker.id, attempt.id, WorkerOutcome.SUCCESS, result="first").outcome is WorkerOutcome.SUCCESS
    assert store.reconcile_workers(**scope) == 0
    resumed = store.start_worker_attempt(worker.id, "caller", "next", service_owner_id="service-b")
    assert store.reconcile_workers(**scope) == 0
    assert store.settle_worker(worker.id, attempt.id, WorkerOutcome.FAILURE).phase is WorkerPhase.RUNNING
    assert store.get_worker_attempt(worker.id, resumed.id).status == "running"
    assert store.get_worker_attempt(worker.id, attempt.id).result == "first"


def test_worker_input_snapshot_consumes_only_owned_incorporated_messages(store: Store) -> None:
    worker, _ = _start(store)
    unrelated, _ = _start(store, owner="other", service="service-b")
    store.append_worker_input(worker.id, "caller", "incorporated input")
    snapshot = store.list_worker_input_records(worker.id)
    assert [content for _, content in snapshot] == ["incorporated input"]
    store.append_worker_input(worker.id, "caller", "arrived after snapshot")
    store.append_worker_input(unrelated.id, "other", "other caller's message")
    other_id = store.list_worker_input_records(unrelated.id)[0][0]
    with pytest.raises(PermissionError):
        store.consume_worker_inputs(worker.id, "other", [snapshot[0][0]])
    assert store.consume_worker_inputs(worker.id, "caller", [snapshot[0][0], other_id]) == 1
    assert store.list_worker_inputs(worker.id) == ["arrived after snapshot"]
    assert store.list_worker_inputs(unrelated.id) == ["other caller's message"]
    assert store.consume_worker_inputs(worker.id, "caller", [snapshot[0][0]]) == 0


def test_worker_attempt_claim_atomically_consumes_its_input_snapshot(store: Store) -> None:
    worker, _ = _start(store)
    store.append_worker_input(worker.id, "caller", "incorporated")
    snapshot = store.list_worker_input_records(worker.id)
    store.append_worker_input(worker.id, "caller", "arrived after snapshot")
    store.cancel_worker_tree(worker.id, "caller")
    resumed = store.start_worker_attempt(
        worker.id, "caller", "resumed with incorporated", service_owner_id="service-b",
        input_ids=[identity for identity, _ in snapshot],
    )
    assert resumed.status == "running"
    assert store.list_worker_inputs(worker.id) == ["arrived after snapshot"]
    store.cancel_worker_tree(worker.id, "caller")
    with pytest.raises(ValueError, match="input identities changed"):
        store.start_worker_attempt(
            worker.id, "caller", "duplicate incorporation", service_owner_id="service-c",
            input_ids=[identity for identity, _ in snapshot],
        )
    assert len(store.list_worker_attempts(worker.id)) == 2
    assert store.get_worker(worker.id).phase is WorkerPhase.IDLE
    assert store.list_worker_inputs(worker.id) == ["arrived after snapshot"]


def test_worker_attempt_claim_rejects_partial_or_foreign_input_snapshot(store: Store) -> None:
    worker, _ = _start(store)
    other, _ = _start(store, owner="other", service="service-b")
    store.append_worker_input(worker.id, "caller", "must remain queued")
    store.append_worker_input(other.id, "other", "foreign input")
    own_id = store.list_worker_input_records(worker.id)[0][0]
    foreign_id = store.list_worker_input_records(other.id)[0][0]
    store.cancel_worker_tree(worker.id, "caller")
    for invalid_id in (foreign_id, "worker-input-missing"):
        with pytest.raises(ValueError, match="input identities changed"):
            store.start_worker_attempt(
                worker.id, "caller", "invalid resume", service_owner_id="service-c",
                input_ids=[own_id, invalid_id],
            )
        assert len(store.list_worker_attempts(worker.id)) == 1
        assert store.get_worker(worker.id).phase is WorkerPhase.IDLE
        assert store.list_worker_inputs(worker.id) == ["must remain queued"]
        assert store.list_worker_inputs(other.id) == ["foreign input"]
