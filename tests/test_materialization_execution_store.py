"""Execution registration binds exact launch authority and refuses advanced partial history."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_materialization_launch_store import launch as launch_fixture

from famou.evolution import CandidateExecution
from famou.store import Store

JOURNAL = "d" * 64


@pytest.fixture
def batch(tmp_path: Path):
    store, parent, child, task, intent = launch_fixture.__wrapped__(tmp_path)
    store.record_materialization_launch_intent(parent, child, task, intent)
    store.add_artifact(child, task, "prompt.txt", "e" * 64, 100, "prompt")
    execution = CandidateExecution("succeeded", 0, 25, stdout="本地结果", artifacts=("output/result.txt",)).to_dict()
    return store, parent, child, task, intent, execution


def encoded(execution: dict) -> bytes:
    return (json.dumps(execution, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def prepare(batch: Any, *, maximum: int = 100_000) -> None:
    batch[0].prepare_materialization_execution(*batch[1:], journal_sha256=JOURNAL, max_artifact_bytes=maximum)


def commit(batch: Any, *, maximum: int = 100_000) -> None:
    batch[0].commit_materialization_execution(*batch[1:], journal_sha256=JOURNAL, max_artifact_bytes=maximum)


def status(batch: Any, *, journal: str = JOURNAL) -> str:
    return batch[0].materialization_execution_status(*batch[1:], journal_sha256=journal)


def snapshot(store: Store) -> tuple[str, ...]:
    with store._connect() as connection:
        return tuple(connection.iterdump())


def ids(batch: Any) -> dict[str, str]:
    _, parent, child, _, intent, _ = batch
    suffix = hashlib.sha256(f"{parent}\0{child}".encode()).hexdigest()
    executed = hashlib.sha256(f"{parent}\0{child}\0{intent['candidate_sha256']}".encode()).hexdigest()
    return {
        "artifact": "artifact-materialization-execution-" + suffix,
        "prepared": "event-materialization-execution-prepared-" + suffix,
        "recorded": "event-materialization-execution-artifact-recorded-" + suffix,
        "executed": "event-evolved-candidate-executed-" + executed,
        "committed": "event-materialization-execution-committed-" + suffix,
        "launch": "event-materialization-launch-intended-" + suffix,
    }


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "timed_out"])
def test_prepare_atomic_registration_and_exact_replay(batch: Any, monkeypatch: pytest.MonkeyPatch, outcome: str) -> None:
    store, parent, child, task, intent, execution = batch
    execution.update(CandidateExecution(outcome, 0 if outcome == "succeeded" else None, 25).to_dict())
    original_rows = store.list_artifacts(child)
    assert status(batch) == "absent"
    assert not store.has_materialization_execution(parent, child)
    traces = []
    original = store._connect

    def connect():
        connection = original()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    prepare(batch)
    assert status(batch) == "prepared"
    assert store.list_artifacts(child) == original_rows
    assert store.has_materialization_execution(parent, child)
    commit(batch)
    assert status(batch) == "committed"
    assert traces.count("BEGIN IMMEDIATE") == traces.count("PRAGMA synchronous = FULL") == 2
    artifact = next(row for row in store.list_artifacts(child) if row["id"] == ids(batch)["artifact"])
    assert artifact["path"] == intent["attempt_path"] + "/execution.json"
    assert artifact["task_id"] == task and artifact["kind"] == "evolved_candidate_execution"
    assert artifact["size"] == len(encoded(execution))
    assert artifact["sha256"] == hashlib.sha256(encoded(execution)).hexdigest()
    event = next(row for row in store.list_events(child) if row["id"] == ids(batch)["executed"])
    assert event["payload"] == {
        "candidate_id": intent["candidate_id"], "candidate_sha256": intent["candidate_sha256"],
        "status": execution["status"], "exit_code": execution["exit_code"],
        "duration_ms": execution["duration_ms"], "evidence_path": artifact["path"],
    }
    before = snapshot(store)
    prepare(batch)
    commit(batch)
    assert snapshot(store) == before
    assert not Path(store.get_run(child).workspace).exists()


@pytest.mark.parametrize("fault", ["prepared", "artifact", "recorded", "executed", "committed"])
def test_each_write_failure_rolls_back_its_complete_transaction(batch: Any, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    store = batch[0]
    if fault != "prepared":
        prepare(batch)
    if fault == "artifact":
        with store._connect() as connection:
            connection.execute(
                "CREATE TRIGGER fail_execution BEFORE INSERT ON artifacts WHEN NEW.kind='evolved_candidate_execution' "
                "BEGIN SELECT RAISE(ABORT,'private storage diagnostic'); END"
            )
    else:
        original = store._append_event

        def append(connection, run, task, kind, payload, event_id=None):
            result = original(connection, run, task, kind, payload, event_id)
            if event_id == ids(batch)[fault]:
                raise RuntimeError("private post-insert diagnostic")
            return result

        monkeypatch.setattr(store, "_append_event", append)
    before = snapshot(store)
    with pytest.raises(ValueError, match="^materialization_execution_commit_failed$"):
        (prepare if fault == "prepared" else commit)(batch)
    assert snapshot(store) == before
    assert status(batch) == ("absent" if fault == "prepared" else "prepared")


def test_commit_requires_preparation_and_rejects_ignored_events(batch: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
        commit(batch)
    prepare(batch)
    before = snapshot(batch[0])
    monkeypatch.setattr(batch[0], "_append_event", lambda *a, **k: False)
    with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
        commit(batch)
    assert snapshot(batch[0]) == before


@pytest.mark.parametrize("stage", ["absent", "prepared", "committed"])
@pytest.mark.parametrize("drift", ["missing", "duplicate", "owner", "digest", "intent"])
def test_launch_authority_is_rechecked_for_every_status_and_write(batch: Any, stage: str, drift: str) -> None:
    store, parent, _, _, intent, _ = batch
    if stage != "absent":
        prepare(batch)
    if stage == "committed":
        commit(batch)
    with store._connect() as connection:
        launch_id = ids(batch)["launch"]
        if drift == "missing":
            connection.execute("DELETE FROM events WHERE id=?", (launch_id,))
        elif drift == "duplicate":
            connection.execute("INSERT INTO events SELECT 'duplicate-launch',run_id,task_id,type,payload,created_at FROM events WHERE id=?", (launch_id,))
        elif drift == "owner":
            connection.execute("UPDATE events SET task_id=? WHERE id=?", (store.list_tasks(parent)[0].id, launch_id))
        elif drift == "digest":
            value = json.loads(connection.execute("SELECT payload FROM events WHERE id=?", (launch_id,)).fetchone()[0])
            value["intent_sha256"] = "f" * 64
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(value), launch_id))
        else:
            intent["runner_sha256"] = "f" * 64
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(store) == before


@pytest.mark.parametrize("record", ["prepared", "artifact", "recorded", "executed", "committed"])
def test_committed_missing_records_are_never_rebuilt(batch: Any, record: str) -> None:
    prepare(batch)
    commit(batch)
    table = "artifacts" if record == "artifact" else "events"
    with batch[0]._connect() as connection:
        connection.execute(f"DELETE FROM {table} WHERE id=?", (ids(batch)[record],))
    before = snapshot(batch[0])
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(batch[0]) == before


@pytest.mark.parametrize("record", ["artifact", "recorded", "executed", "committed"])
def test_partial_terminal_batch_cannot_be_completed_piecemeal(batch: Any, record: str) -> None:
    prepare(batch)
    commit(batch)
    with batch[0]._connect() as connection:
        for key in ("artifact", "recorded", "executed", "committed"):
            if key != record:
                table = "artifacts" if key == "artifact" else "events"
                connection.execute(f"DELETE FROM {table} WHERE id=?", (ids(batch)[key],))
    before = snapshot(batch[0])
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(batch[0]) == before


@pytest.mark.parametrize("evidence", [
    "output_event", "output_ack", "parent_terminal", "child_terminal_prepared", "child_terminal_artifact",
    "child_output_artifact", "child_orphan_output_event", "parent_reserved_output", "parent_reserved_output_event", "foreign_fixed_event",
])
@pytest.mark.parametrize("prepared", [False, True])
def test_downstream_evidence_blocks_absent_batch_reconstruction(batch: Any, evidence: str, prepared: bool) -> None:
    store, parent, child, task, _, _ = batch
    if prepared:
        prepare(batch)
    suffix = hashlib.sha256(f"{parent}\0{child}".encode()).hexdigest()
    parent_task = store.list_tasks(parent)[0].id
    path = "output/result.txt"
    output_id = "artifact-output-publication-" + hashlib.sha256(f"{parent}\0{child}\0{path}".encode()).hexdigest()
    if evidence in {"output_event", "output_ack", "parent_terminal"}:
        kind = {"output_event": "evolved_outputs_promoted", "output_ack": "output_publication_committed", "parent_terminal": "evolved_candidate_materialized"}[evidence]
        store.append_event(parent, kind, {"evolution_run_id": child})
    elif evidence == "child_terminal_prepared":
        store.append_event(child, "materialization_publication_prepared", {"evolution_run_id": child}, task)
    elif evidence == "foreign_fixed_event":
        store.append_event(child, "unrelated", {}, task, "event-evolved-outputs-promoted-" + suffix)
    elif evidence == "parent_reserved_output_event":
        store.append_event(parent, "artifact_recorded", {"artifact_id": output_id, "path": path}, parent_task)
    else:
        owner_run = parent if evidence == "parent_reserved_output" else child
        owner_task = parent_task if owner_run == parent else task
        artifact_path = "evolution/materialization/result.json" if evidence == "child_terminal_artifact" else path
        kind = "evolved_materialization" if evidence == "child_terminal_artifact" else "output"
        artifact_id = store.add_artifact(owner_run, owner_task, artifact_path, "f" * 64, 1, kind)
        if evidence == "parent_reserved_output":
            with store._connect() as connection:
                connection.execute("UPDATE artifacts SET id=? WHERE id=?", (output_id, artifact_id))
        elif evidence == "child_orphan_output_event":
            with store._connect() as connection:
                connection.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(store) == before


def test_another_child_output_does_not_block_this_execution(batch: Any) -> None:
    store, parent, child, _, _, _ = batch
    other = store.create_run("another child")
    owner = store.list_tasks(parent)[0].id
    path = "output/shared.txt"
    artifact = store.add_artifact(parent, owner, path, "f" * 64, 2, "output")
    other_id = "artifact-output-publication-" + hashlib.sha256(f"{parent}\0{other.id}\0{path}".encode()).hexdigest()
    with store._connect() as connection:
        connection.execute("UPDATE artifacts SET id=? WHERE id=?", (other_id, artifact))
    for kind in ("evolved_outputs_promoted", "output_publication_committed", "evolved_candidate_materialized"):
        store.append_event(parent, kind, {"evolution_run_id": other.id})
    prepare(batch)
    commit(batch)
    assert status(batch) == "committed"
    # This child's later publication is valid once its execution batch is intact.
    store.append_event(parent, "output_publication_committed", {"evolution_run_id": child})
    assert status(batch) == "committed"
    prepare(batch)
    commit(batch)


@pytest.mark.parametrize("legacy", ["artifact", "executed", "recorded"])
def test_ordinary_execution_evidence_stays_legacy_and_cannot_be_prepared(batch: Any, legacy: str) -> None:
    store, parent, child, task, intent, _ = batch
    path = intent["attempt_path"] + "/execution.json"
    if legacy == "artifact":
        store.add_artifact(child, task, path, "f" * 64, 10, "evolved_candidate_execution")
    else:
        kind = "evolved_candidate_executed" if legacy == "executed" else "artifact_recorded"
        store.append_event(child, kind, {"path": path, "candidate_id": intent["candidate_id"]}, task)
    assert not store.has_materialization_execution(parent, child)
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(store) == before


@pytest.mark.parametrize(("field", "value"), [
    ("schema_version", 1), ("duration_ms", True), ("duration_ms", 2.5), ("exit_code", False),
    ("stdout_bytes", 1), ("stderr_bytes", False), ("error", " padded "), ("stdout", "x" * 20000),
    ("artifacts", ["output//bad.txt"]), ("artifacts", ["../bad.txt"]), ("extra", True),
    ("duration_ms", float("nan")), ("duration_ms", float("inf")),
])
def test_execution_requires_exact_full_normalized_schema(batch: Any, field: str, value: Any) -> None:
    batch[-1][field] = value
    before = snapshot(batch[0])
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(batch[0]) == before


def test_execution_canonical_size_bound_and_transaction_budget(batch: Any) -> None:
    store, _, child, task, _, execution = batch
    size = len(encoded(execution))
    with pytest.raises(ValueError, match="^materialization_execution_budget_exceeded$"):
        prepare(batch, maximum=100 + size - 1)
    prepare(batch, maximum=100 + size)
    store.add_artifact(child, task, "extra.txt", "f" * 64, 1)
    before = snapshot(store)
    with pytest.raises(ValueError, match="^materialization_execution_budget_exceeded$"):
        commit(batch, maximum=100 + size)
    assert snapshot(store) == before
    commit(batch, maximum=101 + size)
    execution["artifacts"] = [f"output/{index}-" + "x" * 2200 for index in range(32)]
    assert len(encoded(execution)) > 64 * 1024
    with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
        status(batch)


@pytest.mark.parametrize("drift", ["duplicate_event", "duplicate_artifact", "foreign_artifact", "foreign_event", "wrong_hash", "journal"])
def test_identity_conflicts_never_repair_committed_execution(batch: Any, drift: str) -> None:
    store, parent, _, _, _, _ = batch
    prepare(batch)
    commit(batch)
    identity = ids(batch)
    with store._connect() as connection:
        if drift == "duplicate_event":
            connection.execute("INSERT INTO events SELECT 'duplicate',run_id,task_id,type,payload,created_at FROM events WHERE id=?", (identity["prepared"],))
        elif drift == "duplicate_artifact":
            connection.execute("INSERT INTO artifacts SELECT 'duplicate',run_id,task_id,path,sha256,size,kind,created_at FROM artifacts WHERE id=?", (identity["artifact"],))
        elif drift == "foreign_artifact":
            connection.execute("UPDATE artifacts SET run_id=? WHERE id=?", (parent, identity["artifact"]))
        elif drift == "foreign_event":
            connection.execute("UPDATE events SET run_id=? WHERE id=?", (parent, identity["prepared"]))
        elif drift == "wrong_hash":
            connection.execute("UPDATE artifacts SET sha256=? WHERE id=?", ("f" * 64, identity["artifact"]))
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            if drift == "journal":
                store.materialization_execution_status(*batch[1:], journal_sha256="f" * 64)
            else:
                operation(batch)
    assert snapshot(store) == before


@pytest.mark.parametrize("raw", ["{", "[]", '{"size":NaN}', '{"size":1e999}', '{"size":1,"size":2}'])
def test_event_json_corruption_is_not_partial_preparation(batch: Any, raw: str) -> None:
    prepare(batch)
    with batch[0]._connect() as connection:
        connection.execute("UPDATE events SET payload=? WHERE id=?", (raw, ids(batch)["prepared"]))
    before = snapshot(batch[0])
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
            operation(batch)
    assert snapshot(batch[0]) == before


@pytest.mark.parametrize("record", ["artifact", "prepared", "recorded", "committed"])
def test_modern_probe_recognizes_reserved_identity_after_other_evidence_loss(batch: Any, record: str) -> None:
    store, parent, child, _, _, _ = batch
    prepare(batch)
    commit(batch)
    with store._connect() as connection:
        for key in ("artifact", "prepared", "recorded", "executed", "committed"):
            table = "artifacts" if key == "artifact" else "events"
            if key != record:
                connection.execute(f"DELETE FROM {table} WHERE id=?", (ids(batch)[key],))
            else:
                connection.execute(f"UPDATE {table} SET run_id=? WHERE id=?", (parent, ids(batch)[key]))
                if table == "events":
                    connection.execute("UPDATE events SET type='unrelated',payload='bad JSON' WHERE id=?", (ids(batch)[key],))
    assert store.has_materialization_execution(parent, child)


def test_readers_use_single_readonly_snapshots_and_never_create_database(batch: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, parent, child, task, intent, execution = batch
    original = sqlite3.connect
    calls, traces = [], []

    def connect(database, **kwargs):
        calls.append(database)
        connection = original(database, **kwargs)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert status(batch) == "absent"
    assert not store.has_materialization_execution(parent, child)
    assert len(calls) == 2 and all(path.endswith("?mode=ro") for path in calls)
    assert traces.count("BEGIN") == 2
    missing = Store(tmp_path / "missing" / "state.db")
    with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
        missing.materialization_execution_status(parent, child, task, intent, execution, journal_sha256=JOURNAL)
    with pytest.raises(ValueError, match="^materialization_execution_ledger_mismatch$"):
        missing.has_materialization_execution(parent, child)
    assert not (tmp_path / "missing").exists()
