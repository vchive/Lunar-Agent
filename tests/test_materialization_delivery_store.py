"""Delivery plans require exact committed execution before publication can resume."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_materialization_execution_store import (
    JOURNAL,
    commit,
    encoded,
    ids,
    prepare,
    snapshot,
    status,
)
from test_materialization_execution_store import batch as execution_fixture

from lunar_evolution.evolution import CandidateExecution
from lunar_evolution.store import Store

ERROR = "^materialization_delivery_ledger_mismatch$"
PLAN_PATH = "evolution/materialization/.delivery-publication/plan.json"


@pytest.fixture
def delivery(tmp_path: Path):
    batch = execution_fixture.__wrapped__(tmp_path)
    _, parent, child, task, intent, execution = batch
    prepare(batch)
    commit(batch)
    result = {
        "schema_version": "1", "status": "succeeded", "parent_run_id": parent,
        "evolution_run_id": child,
        **{key: intent[key] for key in ("contract_sha256", "candidate_id", "candidate_path", "candidate_sha256", "attempt_path")},
        "execution": {"status": execution["status"], "exit_code": execution["exit_code"],
                      "duration_ms": execution["duration_ms"], "evidence_path": intent["attempt_path"] + "/execution.json"},
        "validation": {"passed": True, "evidence": [], "reason": "输出验证通过", "details": {"score": 0.875}},
        "outputs": [], "error": None,
    }
    plan = {
        "schema_version": "1", "parent_run_id": parent, "evolution_run_id": child, "task_id": task,
        "launch_intent_sha256": hashlib.sha256(encoded(intent)).hexdigest(),
        "execution_journal_sha256": JOURNAL, "execution_sha256": hashlib.sha256(encoded(execution)).hexdigest(),
        "result": result,
        "outputs": [{"path": "output/result.txt", "format": "text", "fields": [], "required": True,
                     "size": 16, "sha256": "a" * 64}],
    }
    return (*batch, plan)


def event_id(delivery: Any) -> str:
    return "event-materialization-delivery-prepared-" + hashlib.sha256(
        f"{delivery[1]}\0{delivery[2]}".encode()
    ).hexdigest()


def record(delivery: Any) -> None:
    delivery[0].record_materialization_delivery(*delivery[1:])


def recorded(delivery: Any) -> bool:
    return delivery[0].materialization_delivery_recorded(*delivery[1:])


def reject_without_changes(delivery: Any) -> None:
    before = snapshot(delivery[0])
    for operation in (recorded, record):
        with pytest.raises(ValueError, match=ERROR):
            operation(delivery)
    assert snapshot(delivery[0]) == before


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "timed_out", "validation_failed"])
def test_registration_and_replay_bind_exact_plan_without_artifact_rows(delivery: Any, monkeypatch: pytest.MonkeyPatch, outcome: str) -> None:
    store, parent, child, task, _, execution, plan = delivery
    if outcome != "succeeded":
        if outcome != "validation_failed":
            execution.update(CandidateExecution(outcome, None, 25).to_dict())
            with store._connect() as connection:
                for name, identity in ids(delivery[:-1]).items():
                    if name != "launch":
                        connection.execute(f"DELETE FROM {'artifacts' if name == 'artifact' else 'events'} WHERE id=?", (identity,))
            prepare(delivery[:-1])
            commit(delivery[:-1])
            plan["execution_sha256"] = hashlib.sha256(encoded(execution)).hexdigest()
            plan["result"]["execution"].update({key: execution[key] for key in ("status", "exit_code", "duration_ms")})
        plan["result"].update(status="failed", error=outcome)
        plan["result"]["validation"]["passed"] = False
        plan["outputs"] = []
    artifacts = store.list_artifacts(child)
    assert not recorded(delivery)
    assert not store.has_materialization_delivery(parent, child)
    traces = []
    original = store._connect

    def connect():
        connection = original()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    record(delivery)
    assert traces.count("BEGIN IMMEDIATE") == traces.count("PRAGMA synchronous = FULL") == 1
    assert store.has_materialization_delivery(parent, child)
    assert recorded(delivery)
    assert store.list_artifacts(child) == artifacts
    events = [row for row in store.list_events(child) if row["type"].startswith("materialization_delivery")]
    assert len(events) == 1
    event = events[0]
    assert event["id"] == event_id(delivery) and event["task_id"] == task
    assert event["type"] == "materialization_delivery_prepared"
    assert event["payload"] == {
        "parent_run_id": parent, "evolution_run_id": child, "owner_task_id": task,
        "plan_path": PLAN_PATH, "plan_sha256": hashlib.sha256(encoded(plan)).hexdigest(),
        "plan_size": len(encoded(plan)), "execution_journal_sha256": JOURNAL,
        "execution_sha256": plan["execution_sha256"],
    }
    before = snapshot(store)
    record(delivery)
    assert snapshot(store) == before
    assert not Path(store.get_run(child).workspace).exists()


@pytest.mark.parametrize("path,value", [
    (("schema_version",), 1), (("schema_version",), True), (("extra",), None),
    (("parent_run_id",), "different"), (("evolution_run_id",), "different"), (("task_id",), "different"),
    (("launch_intent_sha256",), "b" * 64), (("launch_intent_sha256",), True),
    (("execution_sha256",), "b" * 64), (("execution_journal_sha256",), "b" * 64),
    (("execution_journal_sha256",), "D" * 64), (("execution_journal_sha256",), None),
    (("result",), {}), (("result", "extra"), None), (("result", "schema_version"), True),
    (("result", "parent_run_id"), "different"), (("result", "evolution_run_id"), "different"),
    (("result", "contract_sha256"), "b" * 64), (("result", "candidate_id"), "different"),
    (("result", "candidate_path"), "different.py"), (("result", "candidate_sha256"), "f" * 64),
    (("result", "attempt_path"), "different"), (("result", "status"), "timed_out"),
    (("result", "outputs"), ["output/result.txt"]), (("result", "outputs"), None),
    (("result", "execution", "status"), "failed"), (("result", "execution", "duration_ms"), 25.0),
    (("result", "execution", "exit_code"), False), (("result", "execution", "evidence_path"), None),
    (("result", "execution", "extra"), None), (("result", "error"), "unexpected"),
    (("result", "validation", "extra"), None), (("result", "validation", "passed"), False),
    (("result", "validation", "passed"), 1), (("result", "validation", "evidence"), "bad"),
    (("result", "validation", "evidence"), [1]), (("result", "validation", "reason"), 1),
    (("result", "validation", "details"), []), (("result", "validation", "details", "score"), float("nan")),
    (("result", "validation", "details", "score"), float("inf")),
    (("outputs",), None), (("outputs", 0), {}), (("outputs", 0, "artifact_id"), "unplanned-owner"),
    (("outputs", 0, "path"), "../outside.txt"), (("outputs", 0, "path"), "output//bad.txt"),
    (("outputs", 0, "path"), "output/./bad.txt"), (("outputs", 0, "path"), "output/../bad.txt"),
    (("outputs", 0, "path"), "/output/bad.txt"), (("outputs", 0, "path"), "output\\bad.txt"),
    (("outputs", 0, "format"), "TEXT"), (("outputs", 0, "fields"), ()),
    (("outputs", 0, "fields"), ["extra"]), (("outputs", 0, "required"), 1),
    (("outputs", 0, "size"), True), (("outputs", 0, "size"), 1.0), (("outputs", 0, "size"), -1),
    (("outputs", 0, "size"), 256 * 1024 + 1), (("outputs", 0, "sha256"), "A" * 64),
    (("outputs", 0, "sha256"), "bad"), (("outputs", 0, "sha256"), 1),
])
def test_noncanonical_or_unbound_plan_rejected_without_writes(delivery: Any, path: tuple, value: Any) -> None:
    target = delivery[-1]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    reject_without_changes(delivery)


@pytest.mark.parametrize("invalid", ["extra_execution", "execution_status", "intent", "missing_plan_key", "duplicate_output", "too_many_outputs", "failed_outputs", "failed_error", "plan_size"])
def test_plan_bounds_and_complete_identity(delivery: Any, invalid: str) -> None:
    _, _, _, _, intent, execution, plan = delivery
    if invalid == "extra_execution":
        execution["extra"] = True
    elif invalid == "execution_status":
        execution["status"] = "failed"
    elif invalid == "intent":
        intent["runner_sha256"] = "f" * 64
    elif invalid == "missing_plan_key":
        del plan["execution_sha256"]
    elif invalid == "duplicate_output":
        plan["outputs"] *= 2
    elif invalid == "too_many_outputs":
        plan["outputs"] = [{**plan["outputs"][0], "path": f"output/{index}.txt"} for index in range(33)]
    elif invalid == "failed_outputs":
        plan["result"].update(status="failed", error="failed")
    elif invalid == "failed_error":
        plan["result"].update(status="failed", error="")
        plan["outputs"] = []
    else:
        plan["result"]["validation"]["reason"] = "文" * (64 * 1024)
    reject_without_changes(delivery)


def test_exact_canonical_plan_byte_bound(delivery: Any) -> None:
    plan = delivery[-1]
    plan["result"]["validation"]["reason"] = ""
    plan["result"]["validation"]["reason"] = "x" * (64 * 1024 - len(encoded(plan)))
    assert len(encoded(plan)) == 64 * 1024
    assert not recorded(delivery)
    record(delivery)
    assert recorded(delivery)
    plan["result"]["validation"]["reason"] += "x"
    reject_without_changes(delivery)


@pytest.mark.parametrize("already_recorded", [False, True])
@pytest.mark.parametrize("authority", ["launch", "prepared", "artifact", "recorded", "executed", "committed"])
def test_complete_authority_is_required_even_after_delivery_registration(delivery: Any, authority: str, already_recorded: bool) -> None:
    if already_recorded:
        record(delivery)
    with delivery[0]._connect() as connection:
        table = "artifacts" if authority == "artifact" else "events"
        connection.execute(f"DELETE FROM {table} WHERE id=?", (ids(delivery[:-1])[authority],))
    reject_without_changes(delivery)


@pytest.mark.parametrize("already_recorded", [False, True])
@pytest.mark.parametrize("drift", ["task_owner", "extra_child_task", "missing_parent", "launch_hash", "execution_hash", "execution_owner", "execution_duplicate"])
def test_authority_ownership_and_digests_are_revalidated(delivery: Any, drift: str, already_recorded: bool) -> None:
    store, parent, child, _, _, _, _ = delivery
    if already_recorded:
        record(delivery)
    identity = ids(delivery[:-1])
    with store._connect() as connection:
        if drift == "task_owner":
            connection.execute("UPDATE tasks SET run_id=? WHERE run_id=?", (parent, child))
        elif drift == "extra_child_task":
            connection.execute(
                "INSERT INTO tasks(id,run_id,title,prompt,state,created_at,updated_at) "
                "VALUES('extra-child-task',?,'extra','extra','ready','now','now')", (child,),
            )
        elif drift == "missing_parent":
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DELETE FROM runs WHERE id=?", (parent,))
        elif drift == "launch_hash":
            payload = json.loads(connection.execute("SELECT payload FROM events WHERE id=?", (identity["launch"],)).fetchone()[0])
            payload["intent_sha256"] = "f" * 64
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), identity["launch"]))
        elif drift == "execution_hash":
            connection.execute("UPDATE artifacts SET sha256=? WHERE id=?", ("f" * 64, identity["artifact"]))
        elif drift == "execution_owner":
            connection.execute("UPDATE artifacts SET task_id=? WHERE id=?", (store.list_tasks(parent)[0].id, identity["artifact"]))
        else:
            connection.execute("INSERT INTO events SELECT 'duplicate-execution',run_id,task_id,type,payload,created_at FROM events WHERE id=?", (identity["prepared"],))
    reject_without_changes(delivery)


@pytest.mark.parametrize("drift", ["run", "task", "type", "id", "duplicate", "payload", "extra_payload", "payload_type", "foreign_reserved", "foreign_type"])
def test_conflicting_receipts_never_repaired(delivery: Any, drift: str) -> None:
    store, parent, child, _, _, _, _ = delivery
    record(delivery)
    with store._connect() as connection:
        if drift in {"run", "task", "type", "id"}:
            column = {"run": "run_id", "task": "task_id", "type": "type", "id": "id"}[drift]
            value = {"run": parent, "task": store.list_tasks(parent)[0].id, "type": "unrelated", "id": "wrong-event"}[drift]
            connection.execute(f"UPDATE events SET {column}=? WHERE id=?", (value, event_id(delivery)))
        elif drift == "duplicate":
            connection.execute("INSERT INTO events SELECT 'duplicate',run_id,task_id,type,payload,created_at FROM events WHERE id=?", (event_id(delivery),))
        elif drift in {"payload", "extra_payload", "payload_type"}:
            payload = json.loads(connection.execute("SELECT payload FROM events WHERE id=?", (event_id(delivery),)).fetchone()[0])
            if drift == "payload":
                payload["plan_sha256"] = "f" * 64
            elif drift == "extra_payload":
                payload["extra"] = True
            else:
                payload["plan_size"] = float(payload["plan_size"])
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), event_id(delivery)))
        elif drift == "foreign_reserved":
            connection.execute("UPDATE events SET run_id=?,task_id=NULL,type='unrelated',payload='not JSON' WHERE id=?", (parent, event_id(delivery)))
        else:
            connection.execute("UPDATE events SET id='random-delivery-id',payload='not JSON' WHERE id=?", (event_id(delivery),))
    assert store.has_materialization_delivery(parent, child)
    reject_without_changes(delivery)


@pytest.mark.parametrize("raw", ["{", "[]", '{"plan_size":NaN}', '{"plan_size":1e999}', '{"plan_size":1,"plan_size":2}'])
def test_malformed_receipt_json_is_rejected(delivery: Any, raw: str) -> None:
    record(delivery)
    with delivery[0]._connect() as connection:
        connection.execute("UPDATE events SET payload=? WHERE id=?", (raw, event_id(delivery)))
    reject_without_changes(delivery)


@pytest.mark.parametrize("fault", ["sql", "after_append", "ignored"])
def test_failed_registration_rolls_back_and_keeps_diagnostics_bounded(delivery: Any, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    store = delivery[0]
    if fault == "sql":
        with store._connect() as connection:
            connection.execute("CREATE TRIGGER fail_delivery BEFORE INSERT ON events WHEN NEW.type='materialization_delivery_prepared' BEGIN SELECT RAISE(ABORT,'private diagnostic'); END")
    else:
        original = store._append_event

        def append(*args, **kwargs):
            if fault == "ignored":
                return False
            original(*args, **kwargs)
            raise RuntimeError("private diagnostic")

        monkeypatch.setattr(store, "_append_event", append)
    before = snapshot(store)
    expected = ERROR if fault == "ignored" else "^materialization_delivery_commit_failed$"
    with pytest.raises(ValueError, match=expected):
        record(delivery)
    assert snapshot(store) == before
    assert not recorded(delivery)


@pytest.mark.parametrize("already_recorded", [False, True])
@pytest.mark.parametrize("evidence", [
    "output_event", "output_ack", "terminal_event", "terminal_prepared", "terminal_committed",
    "terminal_artifact", "output_artifact", "orphan_output_event", "parent_output_artifact",
    "parent_orphan_event", "reserved_event", "child_retyped_output", "parent_retyped_output",
])
def test_downstream_evidence_forbids_missing_plan_registration(delivery: Any, evidence: str, already_recorded: bool) -> None:
    store, parent, child, task, _, _, _ = delivery
    if already_recorded:
        record(delivery)
    parent_task = store.list_tasks(parent)[0].id
    suffix = hashlib.sha256(f"{parent}\0{child}".encode()).hexdigest()
    path = "output/result.txt"
    output_id = store._output_publication_artifact_id(parent, child, path)
    if evidence in {"output_event", "output_ack", "terminal_event"}:
        kind = {"output_event": "evolved_outputs_promoted", "output_ack": "output_publication_committed", "terminal_event": "evolved_candidate_materialized"}[evidence]
        store.append_event(parent, kind, {"evolution_run_id": child})
    elif evidence in {"terminal_prepared", "terminal_committed"}:
        store.append_event(child, "materialization_publication_" + evidence.removeprefix("terminal_"), {}, task)
    elif evidence == "reserved_event":
        store.append_event(parent, "unrelated", {}, parent_task, "event-materialization-publication-prepared-" + suffix)
    elif evidence == "parent_orphan_event":
        store.append_event(parent, "artifact_recorded", {"artifact_id": output_id, "path": path}, parent_task)
    else:
        owner = parent if evidence in {"parent_output_artifact", "parent_retyped_output"} else child
        owner_task = parent_task if owner == parent else task
        artifact_path = "evolution/materialization/result.json" if evidence == "terminal_artifact" else path
        kind = "evolved_materialization" if evidence == "terminal_artifact" else "output"
        artifact_id = store.add_artifact(owner, owner_task, artifact_path, "a" * 64, 16, kind)
        with store._connect() as connection:
            if evidence in {"parent_output_artifact", "parent_retyped_output"}:
                connection.execute("UPDATE artifacts SET id=? WHERE id=?", (output_id, artifact_id))
            elif evidence == "orphan_output_event":
                connection.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))
            if evidence in {"child_retyped_output", "parent_retyped_output"}:
                connection.execute("UPDATE artifacts SET kind='unrelated' WHERE id=?", (output_id if owner == parent else artifact_id,))
                connection.execute("DELETE FROM events WHERE type='artifact_recorded' AND json_extract(payload,'$.artifact_id')=?", (artifact_id,))
    assert store.has_materialization_delivery(parent, child) is already_recorded
    if already_recorded:
        before = snapshot(store)
        assert recorded(delivery)
        record(delivery)
        assert snapshot(store) == before
    else:
        reject_without_changes(delivery)


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("evidence", ["reserved", "type", "foreign_reserved"])
def test_delivery_evidence_blocks_missing_execution_reconstruction(delivery: Any, prepared: bool, evidence: str) -> None:
    store, parent, child, task, _, _, _ = delivery
    with store._connect() as connection:
        for name, identity in ids(delivery[:-1]).items():
            if name not in ({"launch", "prepared"} if prepared else {"launch"}):
                connection.execute(f"DELETE FROM {'artifacts' if name == 'artifact' else 'events'} WHERE id=?", (identity,))
    if evidence == "type":
        store.append_event(child, "materialization_delivery_prepared", {}, task)
    else:
        store.append_event(parent if evidence == "foreign_reserved" else child, "unrelated", {}, None, event_id(delivery))
    assert store.has_materialization_delivery(parent, child)
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(delivery[:-1])
    assert snapshot(store) == before


def test_another_child_parent_outputs_do_not_block_delivery(delivery: Any) -> None:
    store, parent, child, _, _, _, _ = delivery
    other = store.create_run("another child")
    owner = store.list_tasks(parent)[0].id
    path = "output/shared.txt"
    artifact_id = store.add_artifact(parent, owner, path, "f" * 64, 2, "output")
    other_output_id = store._output_publication_artifact_id(parent, other.id, path)
    with store._connect() as connection:
        connection.execute("UPDATE artifacts SET id=? WHERE id=?", (other_output_id, artifact_id))
    store.append_event(parent, "artifact_recorded", {"artifact_id": other_output_id, "path": path}, owner)
    for kind in ("evolved_outputs_promoted", "output_publication_committed", "evolved_candidate_materialized"):
        store.append_event(parent, kind, {"evolution_run_id": other.id})
    assert not recorded(delivery)
    assert not store.has_materialization_delivery(parent, child)
    record(delivery)
    assert recorded(delivery)


def test_legacy_execution_does_not_authorize_delivery(delivery: Any) -> None:
    store, parent, child, _, _, _, _ = delivery
    with store._connect() as connection:
        for key in ("prepared", "committed"):
            connection.execute("DELETE FROM events WHERE id=?", (ids(delivery[:-1])[key],))
    assert not store.has_materialization_delivery(parent, child)
    reject_without_changes(delivery)


def test_readers_use_single_readonly_snapshots_without_creating_database(delivery: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, parent, child, *_ = delivery
    original = sqlite3.connect
    calls, traces = [], []

    def connect(database, **kwargs):
        calls.append(database)
        connection = original(database, **kwargs)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert not recorded(delivery)
    assert not store.has_materialization_delivery(parent, child)
    assert len(calls) == 2 and all(path.endswith("?mode=ro") for path in calls)
    assert traces.count("BEGIN") == 2
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "PRAGMA")) for statement in traces)
    missing = Store(tmp_path / "missing" / "state.db")
    with pytest.raises(ValueError, match=ERROR):
        missing.materialization_delivery_recorded(*delivery[1:])
    with pytest.raises(ValueError, match=ERROR):
        missing.has_materialization_delivery(parent, child)
    assert not (tmp_path / "missing").exists()


def test_concurrent_identical_registration_creates_one_receipt(delivery: Any) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: record(delivery), range(2)))
    assert recorded(delivery)
    assert len([row for row in delivery[0].list_events(delivery[2]) if row["type"] == "materialization_delivery_prepared"]) == 1
