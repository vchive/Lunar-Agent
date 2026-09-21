"""Preparation and atomic terminal ledger publication never repair partial history."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from lunar_evolution.store import Store

JOURNAL = "a" * 64
MARKER = "evolution/materialization/result.json"


def encoded(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


@pytest.fixture
def publication(tmp_path: Path) -> tuple[Store, str, str, str, dict[str, Any]]:
    store = Store(tmp_path / "state.db")
    store.initialize()
    parent = store.create_run("parent", tmp_path / "parent")
    child = store.create_run("child", tmp_path / "child")
    task = store.list_tasks(child.id)[0].id
    payload = {
        "schema_version": "1", "status": "succeeded", "parent_run_id": parent.id,
        "evolution_run_id": child.id, "contract_sha256": "b" * 64,
        "candidate_id": "candidate-1", "candidate_path": "evolution/archive/candidate-1/candidate.py",
        "candidate_sha256": "c" * 64, "attempt_path": "evolution/materialization/candidate-1-cccccccccccc",
        "execution": {"status": "succeeded", "exit_code": 0, "duration_ms": 42,
                      "evidence_path": "evolution/materialization/candidate-1-cccccccccccc/execution.json"},
        "validation": {"passed": True, "evidence": [], "reason": "验证通过", "details": {"score": 0.875}},
        "outputs": [], "error": None,
    }
    # These independent execution records must survive every terminal transaction unchanged.
    store.add_artifact(child.id, task, payload["execution"]["evidence_path"], "d" * 64, 100, "evolved_candidate_execution")
    store.append_event(child.id, "evolved_candidate_executed", {"candidate_id": "candidate-1"}, task)
    return store, parent.id, child.id, task, payload


def prepare(publication: Any, *, maximum: int = 100_000) -> None:
    store, parent, child, task, payload = publication
    store.prepare_materialization_publication(parent, child, task, payload, journal_sha256=JOURNAL, max_artifact_bytes=maximum)


def commit(publication: Any, *, maximum: int = 100_000) -> None:
    store, parent, child, task, payload = publication
    store.commit_materialization_publication(parent, child, task, payload, journal_sha256=JOURNAL, max_artifact_bytes=maximum)


def status(publication: Any, *, journal: str = JOURNAL) -> str:
    store, parent, child, task, payload = publication
    return store.materialization_publication_status(parent, child, task, payload, journal_sha256=journal)


def snapshot(store: Store) -> tuple[str, ...]:
    with store._connect() as connection:
        return tuple(connection.iterdump())


def ids(publication: Any) -> dict[str, str]:
    _, parent, child, _, _ = publication
    suffix = hashlib.sha256(f"{parent}\0{child}".encode()).hexdigest()
    return {
        "artifact": "artifact-materialization-publication-" + suffix,
        "prepared": "event-materialization-publication-prepared-" + suffix,
        "recorded": "event-materialization-artifact-recorded-" + suffix,
        "parent": "event-evolved-materialization-" + suffix,
        "committed": "event-materialization-publication-committed-" + suffix,
    }


def test_prepare_commit_and_exact_replay_preserve_payload_and_execution(publication: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, parent, child, task, payload = publication
    original_artifacts = store.list_artifacts(child)
    original_events = store.list_events(child)
    assert status(publication) == "absent"
    assert not store.has_materialization_publication(parent, child)
    original_connect = store._connect
    traces = []

    def connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    prepare(publication)
    assert status(publication) == "prepared"
    assert store.has_materialization_publication(parent, child)
    assert store.list_artifacts(child) == original_artifacts
    prepared_snapshot = snapshot(store)
    prepare(publication)
    assert snapshot(store) == prepared_snapshot
    commit(publication)
    assert status(publication) == "committed"
    assert traces.count("PRAGMA synchronous = FULL") == 3
    assert traces.count("BEGIN IMMEDIATE") == 3
    artifact = next(row for row in store.list_artifacts(child) if row["id"] == ids(publication)["artifact"])
    assert artifact["path"] == MARKER and artifact["kind"] == "evolved_materialization"
    assert artifact["task_id"] == task
    assert artifact["sha256"] == hashlib.sha256(encoded(payload)).hexdigest()
    assert artifact["size"] == len(encoded(payload))
    parent_event = next(event for event in store.list_events(parent) if event["id"] == ids(publication)["parent"])
    assert parent_event["task_id"] is None and parent_event["type"] == "evolved_candidate_materialized"
    assert parent_event["payload"] == {key: value for key, value in payload.items() if key not in {"parent_run_id", "schema_version"}}
    assert all(event in store.list_events(child) for event in original_events)
    assert all(row in store.list_artifacts(child) for row in original_artifacts)
    completed_snapshot = snapshot(store)
    prepare(publication)
    commit(publication)
    assert snapshot(store) == completed_snapshot
    assert not Path(store.get_run(child).workspace).exists()


@pytest.mark.parametrize("failed_before_execution", [False, True])
def test_failed_results_use_the_same_exact_transaction(publication: Any, failed_before_execution: bool) -> None:
    payload = publication[-1]
    payload["status"], payload["error"] = "failed", "candidate execution failed"
    payload["validation"]["passed"] = False
    payload["execution"]["status"] = "failed"
    payload["execution"]["exit_code"] = None if failed_before_execution else 1
    if failed_before_execution:
        payload["execution"].update(evidence_path=None, duration_ms=0)
    prepare(publication)
    commit(publication)
    assert status(publication) == "committed"


def test_commit_without_preparation_is_refused(publication: Any) -> None:
    before = snapshot(publication[0])
    with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
        commit(publication)
    assert snapshot(publication[0]) == before


@pytest.mark.parametrize("fault", ["artifact", "recorded", "parent", "committed"])
def test_each_terminal_write_failure_rolls_back_whole_batch(publication: Any, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    store, _, _, _, _ = publication
    prepare(publication)
    if fault == "artifact":
        with store._connect() as connection:
            connection.execute(
                "CREATE TRIGGER fail_marker BEFORE INSERT ON artifacts "
                "WHEN NEW.kind = 'evolved_materialization' BEGIN SELECT RAISE(ABORT, 'private diagnostic'); END"
            )
    else:
        original = store._append_event

        def append(connection: Any, run: str, task: str | None, kind: str, payload: Any, event_id: str | None = None) -> bool:
            if event_id == ids(publication)[fault]:
                raise RuntimeError("private diagnostic")
            return original(connection, run, task, kind, payload, event_id)

        monkeypatch.setattr(store, "_append_event", append)
    before = snapshot(store)
    with pytest.raises(ValueError, match="^materialization_publication_commit_failed$"):
        commit(publication)
    assert snapshot(store) == before
    assert status(publication) == "prepared"


@pytest.mark.parametrize("operation", [prepare, commit])
def test_ignored_event_insert_is_not_accepted(publication: Any, monkeypatch: pytest.MonkeyPatch, operation: Any) -> None:
    if operation is commit:
        prepare(publication)
    before = snapshot(publication[0])
    monkeypatch.setattr(publication[0], "_append_event", lambda *a, **k: False)
    with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
        operation(publication)
    assert snapshot(publication[0]) == before


def test_prepare_event_failure_rolls_back_receipt(publication: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store = publication[0]
    before = snapshot(store)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("private preparation failure")

    monkeypatch.setattr(store, "_append_event", fail)
    with pytest.raises(ValueError, match="^materialization_publication_commit_failed$"):
        prepare(publication)
    assert snapshot(store) == before
    assert status(publication) == "absent"


def test_budget_checks_marker_and_existing_child_artifacts_on_both_transactions(publication: Any) -> None:
    store, _, child, task, payload = publication
    size = len(encoded(payload))
    before = snapshot(store)
    with pytest.raises(ValueError, match="^materialization_publication_budget_exceeded$"):
        prepare(publication, maximum=100 + size - 1)
    assert snapshot(store) == before
    prepare(publication, maximum=100 + size)
    store.add_artifact(child, task, "extra.txt", "e" * 64, 1)
    before = snapshot(store)
    with pytest.raises(ValueError, match="^materialization_publication_budget_exceeded$"):
        commit(publication, maximum=100 + size)
    assert snapshot(store) == before
    assert status(publication) == "prepared"
    commit(publication, maximum=101 + size)
    assert status(publication) == "committed"


@pytest.mark.parametrize("stage", ["absent", "prepared", "committed"])
@pytest.mark.parametrize("drift", ["parent_missing", "child_missing", "foreign_task", "payload_parent", "payload_child"])
def test_owner_and_payload_identity_drift_never_write(publication: Any, stage: str, drift: str) -> None:
    store, parent, child, task, payload = publication
    if stage != "absent":
        prepare(publication)
    if stage == "committed":
        commit(publication)
    if drift == "parent_missing":
        parent, payload["parent_run_id"] = "missing", "missing"
    elif drift == "child_missing":
        child, payload["evolution_run_id"] = "missing", "missing"
    elif drift == "foreign_task":
        task = store.list_tasks(parent)[0].id
    elif drift == "payload_parent":
        payload["parent_run_id"] = "wrong"
    else:
        payload["evolution_run_id"] = "wrong"
    changed = store, parent, child, task, payload
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(changed)
    assert snapshot(store) == before


@pytest.mark.parametrize("record", ["artifact", "prepared", "recorded", "parent", "committed"])
def test_missing_committed_record_is_partial_not_repairable(publication: Any, record: str) -> None:
    store = publication[0]
    prepare(publication)
    commit(publication)
    table = "artifacts" if record == "artifact" else "events"
    with store._connect() as connection:
        connection.execute(f"DELETE FROM {table} WHERE id = ?", (ids(publication)[record],))
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store) == before


@pytest.mark.parametrize("record", ["artifact", "recorded", "parent", "committed"])
def test_partial_terminal_record_after_preparation_is_never_completed(publication: Any, record: str) -> None:
    store = publication[0]
    prepare(publication)
    commit(publication)
    identity = ids(publication)
    with store._connect() as connection:
        for key in ("artifact", "recorded", "parent", "committed"):
            if key != record:
                table = "artifacts" if key == "artifact" else "events"
                connection.execute(f"DELETE FROM {table} WHERE id = ?", (identity[key],))
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store) == before


@pytest.mark.parametrize("legacy", ["artifact", "parent_event", "artifact_event"])
def test_legacy_terminal_records_are_not_modern_preparation(publication: Any, legacy: str) -> None:
    store, parent, child, task, payload = publication
    if legacy == "artifact":
        store.add_artifact(child, task, MARKER, hashlib.sha256(encoded(payload)).hexdigest(), len(encoded(payload)), "evolved_materialization")
    elif legacy == "parent_event":
        store.append_event(parent, "evolved_candidate_materialized", {"evolution_run_id": child})
    else:
        store.append_event(child, "artifact_recorded", {"artifact_id": "legacy", "path": MARKER, "sha256": "f" * 64, "size": 100}, task)
    assert not store.has_materialization_publication(parent, child)
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store) == before


@pytest.mark.parametrize("drift", ["duplicate_event", "duplicate_artifact", "wrong_hash", "wrong_task", "wrong_kind", "wrong_journal"])
def test_committed_drift_rejects_exact_replay(publication: Any, drift: str) -> None:
    store = publication[0]
    prepare(publication)
    commit(publication)
    identity = ids(publication)
    with store._connect() as connection:
        if drift == "duplicate_event":
            connection.execute("INSERT INTO events SELECT 'duplicate-event',run_id,task_id,type,payload,created_at FROM events WHERE id = ?", (identity["prepared"],))
        elif drift == "duplicate_artifact":
            connection.execute("INSERT INTO artifacts SELECT 'duplicate-artifact',run_id,task_id,path,sha256,size,kind,created_at FROM artifacts WHERE id = ?", (identity["artifact"],))
        elif drift == "wrong_hash":
            connection.execute("UPDATE artifacts SET sha256 = ? WHERE id = ?", ("f" * 64, identity["artifact"]))
        elif drift == "wrong_kind":
            connection.execute("UPDATE artifacts SET kind = 'result' WHERE id = ?", (identity["artifact"],))
        elif drift == "wrong_task":
            other = store.list_tasks(publication[1])[0].id
            connection.execute("UPDATE events SET task_id = ? WHERE id = ?", (other, identity["prepared"]))
        else:
            value = json.loads(connection.execute("SELECT payload FROM events WHERE id = ?", (identity["prepared"],)).fetchone()[0])
            value["journal_sha256"] = "f" * 64
            connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(value), identity["prepared"]))
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store) == before


@pytest.mark.parametrize("raw", ["{", "[]", '{"score":NaN}', '{"score":Infinity}', '{"score":1e999}', '{"score":1,"score":2}'])
def test_strict_event_json_rejects_nonfinite_and_duplicate_keys(publication: Any, raw: str) -> None:
    store = publication[0]
    prepare(publication)
    commit(publication)
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (raw, ids(publication)["parent"]))
    before = snapshot(store)
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store) == before


@pytest.mark.parametrize("invalid", ["nan", "infinite", "oversize", "schema", "path", "attempt"])
def test_invalid_result_payload_is_rejected_before_writes(publication: Any, invalid: str) -> None:
    payload = publication[-1]
    if invalid in {"nan", "infinite"}:
        payload["validation"]["details"]["score"] = float("nan" if invalid == "nan" else "inf")
    elif invalid == "oversize":
        payload["error"] = "x" * (64 * 1024)
    elif invalid == "schema":
        payload["schema_version"] = 1
    elif invalid == "path":
        payload["candidate_path"] = "../candidate.py"
    else:
        payload["attempt_path"] = "evolution/materialization/wrong"
    before = snapshot(publication[0])
    for operation in (status, prepare, commit):
        with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(publication[0]) == before


@pytest.mark.parametrize("record", ["artifact", "prepared", "recorded", "committed"])
def test_has_detects_each_reserved_identity_even_after_owner_or_type_drift(publication: Any, record: str) -> None:
    store, parent, child, _, _ = publication
    prepare(publication)
    commit(publication)
    identity = ids(publication)
    with store._connect() as connection:
        for key, value in identity.items():
            table = "artifacts" if key == "artifact" else "events"
            if key == record:
                connection.execute(f"UPDATE {table} SET run_id = ? WHERE id = ?", (parent, value))
                if table == "events":
                    connection.execute("UPDATE events SET type = 'unrelated', payload = 'invalid' WHERE id = ?", (value,))
            else:
                connection.execute(f"DELETE FROM {table} WHERE id = ?", (value,))
    before = snapshot(store)
    assert store.has_materialization_publication(parent, child)
    assert snapshot(store) == before


@pytest.mark.parametrize("kind", ["materialization_publication_prepared", "materialization_publication_committed", "artifact_recorded"])
def test_has_detects_logical_evidence_without_the_fixed_event_id(publication: Any, kind: str) -> None:
    store, parent, child, task, _ = publication
    value = {"artifact_id": ids(publication)["artifact"]} if kind == "artifact_recorded" else {"parent_run_id": parent, "evolution_run_id": child}
    store.append_event(child, kind, value, task)
    assert store.has_materialization_publication(parent, child)


def test_read_apis_use_readonly_snapshots_and_never_create_missing_database(publication: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, parent, child, task, payload = publication
    original = sqlite3.connect
    calls, traces = [], []

    def connect(database: str, **kwargs: Any) -> sqlite3.Connection:
        calls.append(database)
        connection = original(database, **kwargs)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert status(publication) == "absent"
    assert not store.has_materialization_publication(parent, child)
    assert len(calls) == 2 and all(path.endswith("?mode=ro") for path in calls)
    assert traces.count("BEGIN") == 2
    absent = Store(tmp_path / "absent" / "state.db")
    with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
        absent.has_materialization_publication(parent, child)
    with pytest.raises(ValueError, match="^materialization_publication_ledger_mismatch$"):
        absent.materialization_publication_status(parent, child, task, payload, journal_sha256=JOURNAL)
    assert not (tmp_path / "absent").exists()
