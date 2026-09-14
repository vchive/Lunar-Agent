"""A launch ledger event is durable evidence, never a replayable execution permit."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from famou.store import Store


@pytest.fixture
def launch(tmp_path: Path) -> tuple[Store, str, str, str, dict[str, Any]]:
    store = Store(tmp_path / "state.db")
    store.initialize()
    parent = store.create_run("parent", tmp_path / "parent")
    child = store.create_run("child", tmp_path / "child")
    task = store.list_tasks(child.id)[0].id
    intent = {
        "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
        "task_id": task, "contract_sha256": "a" * 64, "strategy": "population",
        "candidate_id": "candidate-1", "candidate_path": "evolution/archive/candidate-1/candidate.py",
        "candidate_sha256": "b" * 64, "attempt_path": "evolution/materialization/candidate-1-bbbbbbbbbbbb",
        "runner_sha256": "c" * 64, "timeout_seconds": 12.5,
    }
    return store, parent.id, child.id, task, intent


def record(launch: Any) -> None:
    store, parent, child, task, intent = launch
    store.record_materialization_launch_intent(parent, child, task, intent)


def recorded(launch: Any) -> bool:
    store, parent, child, task, intent = launch
    return store.materialization_launch_intent_recorded(parent, child, task, intent)


def event_id(launch: Any) -> str:
    return "event-materialization-launch-intended-" + hashlib.sha256(f"{launch[1]}\0{launch[2]}".encode()).hexdigest()


def snapshot(store: Store) -> tuple[str, ...]:
    with store._connect() as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize("strategy", ["population", "openevolve"])
def test_launch_intent_is_exact_durable_and_idempotent(launch: Any, monkeypatch: pytest.MonkeyPatch, strategy: str) -> None:
    store, parent, child, task, intent = launch
    intent["strategy"] = strategy
    assert not recorded(launch)
    assert not store.has_materialization_launch_intent(parent, child)
    original = store._connect
    traces = []

    def connect() -> sqlite3.Connection:
        connection = original()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    record(launch)
    assert "PRAGMA synchronous = FULL" in traces and "BEGIN IMMEDIATE" in traces
    assert recorded(launch)
    assert store.has_materialization_launch_intent(parent, child)
    events = [row for row in store.list_events(child) if row["type"] == "materialization_launch_intended"]
    assert len(events) == 1
    content = (json.dumps(intent, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    assert events[0]["id"] == event_id(launch) and events[0]["task_id"] == task
    assert events[0]["payload"] == {
        "parent_run_id": parent, "evolution_run_id": child,
        "intent_path": "evolution/materialization/launch-intent.json",
        "intent_sha256": hashlib.sha256(content).hexdigest(), "intent_size": len(content),
    }
    before = snapshot(store)
    record(launch)
    assert snapshot(store) == before
    assert store.list_artifacts(child) == []
    assert not Path(store.get_run(child).workspace).exists()


@pytest.mark.parametrize("fault", ["exception", "ignored", "after_insert", "sql"])
def test_intent_write_failure_rolls_back_without_private_diagnostics(launch: Any, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    store = launch[0]
    original = store._append_event
    if fault == "sql":
        with store._connect() as connection:
            connection.execute(
                "CREATE TRIGGER fail_intent BEFORE INSERT ON events "
                "WHEN NEW.type = 'materialization_launch_intended' BEGIN SELECT RAISE(ABORT, 'private diagnostic'); END"
            )
    else:
        def append(*args: Any, **kwargs: Any) -> bool:
            if fault == "ignored":
                return False
            if fault == "after_insert":
                original(*args, **kwargs)
            raise OSError("private path or credential")

        monkeypatch.setattr(store, "_append_event", append)
    before = snapshot(store)
    code = "ledger_mismatch" if fault == "ignored" else "commit_failed"
    with pytest.raises(ValueError, match=f"^materialization_launch_{code}$"):
        record(launch)
    assert snapshot(store) == before
    assert not recorded(launch)


@pytest.mark.parametrize("drift", ["parent_missing", "child_missing", "foreign_task", "multiple_child_tasks", "same_run"])
@pytest.mark.parametrize("existing", [False, True])
def test_ownership_is_checked_on_first_write_and_replay(launch: Any, drift: str, existing: bool) -> None:
    store, parent, child, task, intent = launch
    if existing:
        record(launch)
    if drift == "parent_missing":
        parent = intent["parent_run_id"] = "missing"
    elif drift == "child_missing":
        child = intent["evolution_run_id"] = "missing"
    elif drift == "foreign_task":
        task = intent["task_id"] = store.list_tasks(parent)[0].id
    elif drift == "same_run":
        parent = intent["parent_run_id"] = child
    else:
        with store._connect() as connection:
            connection.execute(
                "INSERT INTO tasks(id,run_id,title,prompt,state,created_at,updated_at) "
                "VALUES('extra-child-task',?,'extra','extra','ready','now','now')", (child,),
            )
    changed = store, parent, child, task, intent
    before = snapshot(store)
    for operation in (recorded, record):
        with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
            operation(changed)
    assert snapshot(store) == before


@pytest.mark.parametrize(("field", "value"), [
    ("schema_version", 1), ("strategy", "loop"), ("strategy", "unknown"),
    ("candidate_id", "../candidate"), ("candidate_id", "x" * 129),
    ("candidate_path", "../candidate.py"), ("candidate_path", "/candidate.py"),
    ("candidate_path", "evolution//candidate.py"), ("candidate_path", "evolution\\candidate.py"),
    ("candidate_path", "x" * 8200), ("attempt_path", "evolution/materialization/wrong"),
    ("contract_sha256", "A" * 64), ("candidate_sha256", "b" * 63), ("runner_sha256", "g" * 64),
    ("timeout_seconds", True), ("timeout_seconds", 0), ("timeout_seconds", -1),
    ("timeout_seconds", 86401), ("timeout_seconds", float("nan")),
    ("timeout_seconds", float("inf")), ("timeout_seconds", "12"),
    ("parent_run_id", "other"), ("evolution_run_id", "other"), ("task_id", "other"),
])
def test_invalid_intent_is_rejected_before_writes(launch: Any, field: str, value: Any) -> None:
    launch[-1][field] = value
    before = snapshot(launch[0])
    for operation in (recorded, record):
        with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
            operation(launch)
    assert snapshot(launch[0]) == before


@pytest.mark.parametrize("change", ["missing", "extra", "numeric_timeout", "candidate", "strategy", "runner"])
def test_intent_shape_and_content_must_match_exactly_on_replay(launch: Any, change: str) -> None:
    record(launch)
    intent = launch[-1]
    if change == "missing":
        intent.pop("runner_sha256")
    elif change == "extra":
        intent["pid"] = 123
    elif change == "numeric_timeout":
        intent["timeout_seconds"] = 12
    elif change == "candidate":
        intent["candidate_path"] = "another/candidate.py"
    elif change == "strategy":
        intent["strategy"] = "openevolve"
    else:
        intent["runner_sha256"] = "d" * 64
    before = snapshot(launch[0])
    for operation in (recorded, record):
        with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
            operation(launch)
    assert snapshot(launch[0]) == before


@pytest.mark.parametrize("drift", ["id", "duplicate", "type", "run", "task", "path", "sha256", "size"])
def test_event_drift_is_never_hidden_by_idempotence(launch: Any, drift: str) -> None:
    store, parent, child, _, _ = launch
    record(launch)
    with store._connect() as connection:
        if drift == "duplicate":
            connection.execute("INSERT INTO events SELECT 'duplicate',run_id,task_id,type,payload,created_at FROM events WHERE id=?", (event_id(launch),))
        elif drift in {"id", "type", "run", "task"}:
            column, value = {
                "id": ("id", "changed-id"), "type": ("type", "changed-type"),
                "run": ("run_id", parent), "task": ("task_id", store.list_tasks(parent)[0].id),
            }[drift]
            connection.execute(f"UPDATE events SET {column}=? WHERE id=?", (value, event_id(launch)))
        else:
            payload = json.loads(connection.execute("SELECT payload FROM events WHERE id=?", (event_id(launch),)).fetchone()[0])
            key = {"path": "intent_path", "sha256": "intent_sha256", "size": "intent_size"}[drift]
            payload[key] = False if drift == "size" else "wrong"
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), event_id(launch)))
    before = snapshot(store)
    for operation in (recorded, record):
        with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
            operation(launch)
    assert store.has_materialization_launch_intent(parent, child)
    assert snapshot(store) == before


@pytest.mark.parametrize("raw", ["not JSON", "[]", '{"size":NaN}', '{"size":Infinity}', '{"size":1e999}', '{"size":1,"size":2}'])
def test_malformed_event_json_is_execution_uncertainty(launch: Any, raw: str) -> None:
    store, parent, child, _, _ = launch
    record(launch)
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload=? WHERE id=?", (raw, event_id(launch)))
    before = snapshot(store)
    for operation in (recorded, record):
        with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
            operation(launch)
    assert store.has_materialization_launch_intent(parent, child)
    assert snapshot(store) == before


def test_has_detects_unclassifiable_child_logical_event(launch: Any) -> None:
    store, parent, child, task, _ = launch
    store.append_event(child, "materialization_launch_intended", {}, task, "unknown-launch-id")
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload='not JSON' WHERE id='unknown-launch-id'")
    assert store.has_materialization_launch_intent(parent, child)
    with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
        recorded(launch)


def test_has_detects_reserved_id_after_cross_run_type_and_payload_drift(launch: Any) -> None:
    store, parent, child, _, _ = launch
    record(launch)
    with store._connect() as connection:
        connection.execute("UPDATE events SET run_id=?,type='unrelated',payload='invalid' WHERE id=?", (parent, event_id(launch)))
    assert store.has_materialization_launch_intent(parent, child)


def test_readonly_apis_use_one_snapshot_each_without_creating_database(launch: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, parent, child, task, intent = launch
    original = sqlite3.connect
    calls, traces = [], []

    def connect(database: str, **kwargs: Any) -> sqlite3.Connection:
        calls.append(database)
        connection = original(database, **kwargs)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert not recorded(launch)
    assert not store.has_materialization_launch_intent(parent, child)
    assert len(calls) == 2 and all(path.endswith("?mode=ro") for path in calls)
    assert traces.count("BEGIN") == 2
    absent = Store(tmp_path / "absent" / "state.db")
    with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
        absent.materialization_launch_intent_recorded(parent, child, task, intent)
    with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
        absent.has_materialization_launch_intent(parent, child)
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("identifier", ["", "x" * 129, "../run", "a\0b"])
def test_probe_rejects_invalid_parent_and_child_ids(launch: Any, identifier: str) -> None:
    store, parent, child, _, _ = launch
    for ids in ((identifier, child), (parent, identifier)):
        with pytest.raises(ValueError, match="^materialization_launch_ledger_mismatch$"):
            store.has_materialization_launch_intent(*ids)
