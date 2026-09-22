"""Provider-free Store fixtures for automatic parent lifecycle ordering."""
from __future__ import annotations

import gc
import json

import pytest

from lunar_evolution._audit_lifecycle import audit_parent_lifecycle
from lunar_evolution._audit_snapshot import audit_snapshot
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionObservation
from lunar_evolution.store import Store


@pytest.fixture
def lifecycle(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    parent = store.create_run("parent", tmp_path / "parent")
    child = store.create_run("child", tmp_path / "child")
    digest = "a" * 64
    store.append_event(parent.id, "evolution_requested", {
        "automatic_lifecycle_version": 1, "bundle_mode": "compiled",
        "solve_wall_timeout": 3000, "solve_wall_timeout_source": "explicit",
    })
    observation = SolveExecutionObservation(store, parent.id, 3000)
    task = store.ensure_orchestration_task(parent.id, title="orchestration", prompt="fixture")
    attempt = store.claim_orchestration_task(task.id, "automatic-solve")
    store.supersede_pending_tasks(parent.id, "fixture orchestration")
    with store._connect() as connection:
        connection.execute("UPDATE tasks SET state = 'superseded' WHERE run_id = ? AND id != ?",
                           (parent.id, task.id))
    store.append_event(parent.id, "automatic_solve_orchestration_started", {
        "task_id": task.id, "attempt_id": attempt.id,
    })
    store.append_event(parent.id, "evolution_linked", {
        "evolution_run_id": child.id, "contract_sha256": digest, "strategy": "population",
    })
    store.append_event(child.id, "evolution_parent_linked", {
        "parent_run_id": parent.id, "contract_sha256": digest,
    })
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = 'succeeded' WHERE id = ?", (child.id,))
    store.append_event(child.id, "run_succeeded", {})
    store.append_event(parent.id, "bundle_candidate_delivered", {
        "schema_version": "1", "mode": "bundle", "status": "succeeded",
        "parent_run_id": parent.id, "evolution_run_id": child.id, "contract_sha256": digest,
        "validation": {"passed": True}, "error": None,
    })
    assert store.finish_task(task.id, attempt.id, True)
    assert store.settle_run(parent.id).status.value == "succeeded"
    observation.observe("delivery", state="terminal", reason="completed")
    return store, {
        "parent_id": parent.id, "child_id": child.id, "orchestration_task_id": task.id,
        "solve_execution_id": observation.execution_id, "contract_sha256": digest,
    }


def audit(lifecycle):
    store, pins = lifecycle
    gc.collect()  # Close fixture Store connections before pinning source DB/WAL metadata.
    with audit_snapshot(store.database) as view:
        return audit_parent_lifecycle(view, **pins)


def mutate_payload(lifecycle, kind, mutate):
    store, pins = lifecycle
    with store._connect() as connection:
        row = connection.execute(
            "SELECT rowid,payload FROM events WHERE run_id = ? AND type = ? ORDER BY rowid LIMIT 1",
            (pins["parent_id"], kind),
        ).fetchone()
        payload = json.loads(row["payload"])
        mutate(payload)
        connection.execute("UPDATE events SET payload = ? WHERE rowid = ?", (json.dumps(payload), row["rowid"]))


def test_complete_lifecycle_is_verified_read_only_and_repeatable(lifecycle):
    store, pins = lifecycle
    original = store.list_events(pins["parent_id"])
    assert audit(lifecycle) == {"status": "verified", "reason": None}
    assert audit(lifecycle) == {"status": "verified", "reason": None}
    assert store.list_events(pins["parent_id"]) == original


@pytest.mark.parametrize("kind", ["run_cancelled", "budget_exceeded", "run_failed"])
def test_terminal_failure_cannot_be_replaced_by_late_success(lifecycle, kind):
    store, pins = lifecycle
    with store._connect() as connection:
        row = connection.execute(
            "SELECT rowid FROM events WHERE run_id = ? AND type = 'run_created'", (pins["parent_id"],),
        ).fetchone()
        connection.execute("UPDATE events SET type = ? WHERE rowid = ?", (kind, row["rowid"]))
    assert audit(lifecycle) == {"status": "failed", "reason": "lifecycle_terminal_failure"}


@pytest.mark.parametrize("reason", ["cancelled", "solve_wall_timeout", "failed", "interrupted"])
def test_old_solve_terminal_cannot_be_replaced_by_later_success(lifecycle, reason):
    mutate_payload(lifecycle, "solve_execution", lambda p: p.update(state="terminal", stopping_reason=reason))
    assert audit(lifecycle)["reason"] == "lifecycle_terminal_failure"


@pytest.mark.parametrize("kind", ["bundle_candidate_delivered", "run_succeeded", "task_succeeded"])
def test_missing_completion_is_unverifiable(lifecycle, kind):
    store, pins = lifecycle
    with store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (pins["parent_id"], kind))
    assert audit(lifecycle)["status"] == "unverifiable"


@pytest.mark.parametrize("kind,mutate,reason", [
    ("evolution_requested", lambda p: p.update(solve_wall_timeout=3001), "lifecycle_policy_mismatch"),
    ("evolution_requested", lambda p: p.update(automatic_lifecycle_version=True), "lifecycle_policy_mismatch"),
    ("evolution_linked", lambda p: p.update(evolution_run_id="elsewhere"), "lifecycle_link_mismatch"),
    ("evolution_linked", lambda p: p.update(contract_sha256="b" * 64), "lifecycle_link_mismatch"),
    ("solve_execution", lambda p: p.update(execution_id="solve-" + "b" * 32), "lifecycle_execution_mismatch"),
    ("solve_execution", lambda p: p.update(policy_seconds=1), "lifecycle_execution_mismatch"),
    ("bundle_candidate_delivered", lambda p: p.update(validation={"passed": False}), "lifecycle_completion_mismatch"),
    ("task_claimed", lambda p: p.update(runtime="ordinary-model"), "lifecycle_attempt_receipt_mismatch"),
])
def test_identity_and_policy_mutations_fail(lifecycle, kind, mutate, reason):
    mutate_payload(lifecycle, kind, mutate)
    assert audit(lifecycle) == {"status": "failed", "reason": reason}


def test_parent_success_before_delivery_fails_even_with_ordered_timestamps(lifecycle):
    store, pins = lifecycle
    with store._connect() as connection:
        row = connection.execute(
            "SELECT rowid FROM events WHERE type = 'run_succeeded' AND run_id = ?", (pins["parent_id"],),
        ).fetchone()
        connection.execute("UPDATE events SET rowid = -1 WHERE rowid = ?", (row["rowid"],))
        first = connection.execute("SELECT min(rowid) FROM events WHERE rowid > 0").fetchone()[0]
        connection.execute("UPDATE events SET rowid = ? WHERE rowid = ?", (row["rowid"], first))
        connection.execute("UPDATE events SET rowid = ? WHERE rowid = -1", (first,))
    assert audit(lifecycle)["reason"] == "lifecycle_completion_order"


def test_attempt_owned_by_ordinary_scheduler_is_rejected(lifecycle):
    store, pins = lifecycle
    with store._connect() as connection:
        connection.execute("UPDATE attempts SET runtime = 'ordinary' WHERE task_id = ?", (pins["orchestration_task_id"],))
    assert audit(lifecycle)["reason"] == "lifecycle_attempt_owner"


def test_orchestration_owner_and_discriminator_are_checked(lifecycle):
    store, pins = lifecycle
    with store._connect() as connection:
        connection.execute("UPDATE tasks SET orchestration = 0 WHERE id = ?", (pins["orchestration_task_id"],))
    assert audit(lifecycle)["reason"] == "lifecycle_orchestration_mismatch"


def test_extra_attempt_not_hidden_by_single_success_receipt(lifecycle):
    store, pins = lifecycle
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO attempts (id,task_id,runtime,status,started_at,heartbeat_at) VALUES (?,?,?,?,?,?)",
            ("extra-attempt", pins["orchestration_task_id"], "automatic-solve", "failed", "now", "now"),
        )
    assert audit(lifecycle)["reason"] == "lifecycle_attempt_count"
