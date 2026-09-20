"""Operator receipts share preparation's durable transaction and cannot change owners."""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_materialization_execution_store import JOURNAL, encoded, ids, snapshot
from test_materialization_execution_store import batch as execution_fixture

from famou.store import Store

ERROR = "^materialization_execution_ledger_mismatch$"


@pytest.fixture
def attested(tmp_path: Path):
    batch = execution_fixture.__wrapped__(tmp_path)
    _, parent, child, task, intent, execution = batch
    receipt = {
        "schema_version": "1", "parent_run_id": parent, "evolution_run_id": child, "task_id": task,
        "launch_intent_sha256": hashlib.sha256(encoded(intent)).hexdigest(),
        "candidate_id": intent["candidate_id"], "candidate_sha256": intent["candidate_sha256"],
        "attempt_path": intent["attempt_path"], "execution_path": intent["attempt_path"] + "/execution.json",
        "execution_sha256": hashlib.sha256(encoded(execution)).hexdigest(), "execution_size": len(encoded(execution)),
        "device": 123, "inode": 456, "nonce": "operator-receipt-" + "a" * 32,
    }
    return *batch, receipt


def event_id(attested: Any) -> str:
    return "event-materialization-execution-attested-" + hashlib.sha256(
        f"{attested[1]}\0{attested[2]}".encode()
    ).hexdigest()


def prepare(attested: Any, *, maximum: int = 100_000) -> None:
    attested[0].prepare_materialization_execution(
        *attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=maximum, attestation=attested[-1],
    )


def commit(attested: Any, *, maximum: int = 100_000) -> None:
    attested[0].commit_materialization_execution(
        *attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=maximum, attestation=attested[-1],
    )


def status(attested: Any) -> str:
    return attested[0].materialization_execution_status(
        *attested[1:-1], journal_sha256=JOURNAL, attestation=attested[-1],
    )


def recorded(attested: Any) -> bool:
    return attested[0].materialization_execution_attestation_recorded(*attested[1:], journal_sha256=JOURNAL)


def reject_without_changes(attested: Any) -> None:
    before = snapshot(attested[0])
    for operation in (status, recorded, prepare, commit):
        with pytest.raises(ValueError, match=ERROR):
            operation(attested)
    assert snapshot(attested[0]) == before


def test_receipt_preparation_and_execution_share_authority(attested: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, parent, child, task, _, _, receipt = attested
    assert not recorded(attested)
    assert not store.has_materialization_execution_attestation(parent, child)
    assert status(attested) == "absent"
    original = store._connect
    traces = []

    def connect():
        connection = original()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    prepare(attested)
    assert traces.count("BEGIN IMMEDIATE") == traces.count("PRAGMA synchronous = FULL") == 1
    assert recorded(attested) and status(attested) == "prepared"
    assert store.has_materialization_execution_attestation(parent, child)
    event = next(row for row in store.list_events(child) if row["id"] == event_id(attested))
    assert event["type"] == "materialization_execution_attested" and event["task_id"] == task
    assert event["payload"] == {
        **receipt, "receipt_sha256": hashlib.sha256(encoded(receipt)).hexdigest(), "journal_sha256": JOURNAL,
    }
    before = snapshot(store)
    prepare(attested)
    assert snapshot(store) == before
    commit(attested)
    assert status(attested) == "committed" and recorded(attested)
    before = snapshot(store)
    prepare(attested)
    commit(attested)
    assert snapshot(store) == before
    assert not Path(store.get_run(child).workspace).exists()


@pytest.mark.parametrize("field,value", [
    ("schema_version", 1), ("schema_version", "2"), ("extra", None),
    ("parent_run_id", "different"), ("evolution_run_id", "different"), ("task_id", "different"),
    ("launch_intent_sha256", "f" * 64), ("launch_intent_sha256", True),
    ("candidate_id", "different"), ("candidate_sha256", "f" * 64),
    ("attempt_path", "different"), ("execution_path", "../execution.json"),
    ("execution_sha256", "f" * 64), ("execution_size", 0), ("execution_size", True),
    ("device", True), ("device", -1), ("device", 1.5), ("device", 2**64),
    ("inode", True), ("inode", -1), ("inode", 1.5), ("inode", 2**64),
    ("nonce", "a" * 31), ("nonce", "a" * 129), ("nonce", "a" * 31 + "/"),
    ("nonce", "a" * 31 + "\n"), ("nonce", "文" * 32), ("nonce", None),
])
def test_noncanonical_receipt_is_rejected_without_writes(attested: Any, field: str, value: Any) -> None:
    attested[-1][field] = value
    reject_without_changes(attested)


@pytest.mark.parametrize("stage", ["prepared", "committed"])
@pytest.mark.parametrize("drift", ["nonce", "device", "inode", "digest", "missing_receipt", "missing_prepared", "duplicate", "owner", "kind", "id", "payload", "duplicate_key"])
def test_receipt_drift_and_fragmented_authority_are_not_repaired(attested: Any, stage: str, drift: str) -> None:
    store = attested[0]
    prepare(attested)
    if stage == "committed":
        commit(attested)
    if drift in {"nonce", "device", "inode"}:
        attested[-1][drift] = "b" * 32 if drift == "nonce" else 321
    else:
        with store._connect() as connection:
            if drift == "missing_receipt":
                connection.execute("DELETE FROM events WHERE id=?", (event_id(attested),))
            elif drift == "missing_prepared":
                connection.execute("DELETE FROM events WHERE id=?", (ids(attested[:-1])["prepared"],))
            elif drift == "duplicate":
                connection.execute(
                    "INSERT INTO events SELECT 'duplicate-receipt',run_id,task_id,type,payload,created_at FROM events WHERE id=?",
                    (event_id(attested),),
                )
            elif drift in {"owner", "kind", "id"}:
                column = {"owner": "task_id", "kind": "type", "id": "id"}[drift]
                value = None if drift == "owner" else "other"
                connection.execute(f"UPDATE events SET {column}=? WHERE id=?", (value, event_id(attested)))
            else:
                row = connection.execute("SELECT payload FROM events WHERE id=?", (event_id(attested),)).fetchone()
                payload = json.loads(row["payload"])
                payload["receipt_sha256"] = "f" * 64
                raw = json.dumps(payload) if drift == "digest" else "PRIVATE invalid payload"
                if drift == "duplicate_key":
                    raw = '{"nonce":"different",' + row["payload"][1:]
                connection.execute("UPDATE events SET payload=? WHERE id=?", (raw, event_id(attested)))
    reject_without_changes(attested)


@pytest.mark.parametrize("stage", ["prepared", "committed"])
def test_normal_calls_cannot_drop_attestation(attested: Any, stage: str) -> None:
    store = attested[0]
    prepare(attested)
    if stage == "committed":
        commit(attested)
    before = snapshot(store)
    with pytest.raises(ValueError, match=ERROR):
        store.materialization_execution_status(*attested[1:-1], journal_sha256=JOURNAL)
    for method in (store.prepare_materialization_execution, store.commit_materialization_execution):
        with pytest.raises(ValueError, match=ERROR):
            method(*attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=100_000)
    assert snapshot(store) == before


@pytest.mark.parametrize("stage", ["prepared", "committed"])
def test_attestation_cannot_be_added_after_ordinary_preparation(attested: Any, stage: str) -> None:
    store = attested[0]
    store.prepare_materialization_execution(*attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=100_000)
    if stage == "committed":
        store.commit_materialization_execution(*attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=100_000)
    reject_without_changes(attested)


@pytest.mark.parametrize("failure", ["prepared", "receipt", "commit"])
def test_transaction_failure_rolls_back_receipt_and_preparation(attested: Any, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    store = attested[0]
    original = store._append_event

    def append(connection, run, task, kind, payload, identity=None):
        result = original(connection, run, task, kind, payload, identity)
        if (failure == "prepared" and kind == "materialization_execution_prepared") or (
            failure == "receipt" and kind == "materialization_execution_attested"
        ):
            raise RuntimeError("PRIVATE injected receipt failure")
        return result

    monkeypatch.setattr(store, "_append_event", append)
    if failure == "commit":
        with store._connect() as connection:
            connection.execute(
                "CREATE TRIGGER fail_receipt BEFORE INSERT ON events WHEN NEW.type='materialization_execution_attested' "
                "BEGIN SELECT RAISE(ABORT,'PRIVATE SQLite failure'); END"
            )
    before = snapshot(store)
    with pytest.raises(ValueError, match="^materialization_execution_commit_failed$"):
        prepare(attested)
    assert snapshot(store) == before and status(attested) == "absent"
    assert not recorded(attested)


@pytest.mark.parametrize("authority", ["launch", "extra_task", "owner"])
def test_exact_launch_authority_is_required_in_same_snapshot(attested: Any, authority: str) -> None:
    store, _, child, _, _, _, _ = attested
    with store._connect() as connection:
        if authority == "launch":
            connection.execute("DELETE FROM events WHERE id=?", (ids(attested[:-1])["launch"],))
        elif authority == "extra_task":
            connection.execute(
                "INSERT INTO tasks(id,run_id,parent_id,title,prompt,state,attempts,result_path,last_error,"
                "dependencies,acceptance,input_question,input_options,input_answer_path,plan_task_id,orchestration,created_at,updated_at) "
                "SELECT 'extra-task',run_id,parent_id,title,prompt,state,attempts,result_path,last_error,"
                "dependencies,acceptance,input_question,input_options,input_answer_path,plan_task_id,orchestration,created_at,updated_at "
                "FROM tasks WHERE run_id=?", (child,),
            )
        else:
            connection.execute("UPDATE events SET task_id=NULL WHERE id=?", (ids(attested[:-1])["launch"],))
    reject_without_changes(attested)


@pytest.mark.parametrize("kind", ["materialization_delivery_prepared", "materialization_publication_prepared", "output", "orphan_output"])
def test_downstream_evidence_refuses_new_authorization(attested: Any, kind: str) -> None:
    store, _, child, task, _, _, _ = attested
    if kind == "output":
        store.add_artifact(child, task, "output/result.txt", "f" * 64, 4, "output")
    else:
        store.append_event(child, "artifact_recorded" if kind == "orphan_output" else kind,
                           {"path": "output/result.txt"} if kind == "orphan_output" else {}, task_id=task)
    reject_without_changes(attested)


def test_probe_does_not_open_writer_or_initialize_missing_database(attested: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = attested[0]
    prepare(attested)
    monkeypatch.setattr(store, "_connect", lambda: pytest.fail("probe opened writer"))
    assert recorded(attested)
    missing = Store(tmp_path / "missing" / "state.sqlite3")
    with pytest.raises(ValueError, match=ERROR):
        missing.materialization_execution_attestation_recorded(*attested[1:], journal_sha256=JOURNAL)
    assert not missing.database.parent.exists()


def test_global_nonce_cannot_be_reused_for_another_pair(attested: Any) -> None:
    store, parent, child, task, intent, execution, receipt = attested
    prepare(attested)
    other_child = child + "-other"
    other_task = task + "-other"
    with store._connect() as connection:
        connection.execute("INSERT INTO runs SELECT ?,goal,status,workspace,created_at,updated_at,runner_pid,runner_pgid,"
                           "current_plan_id,current_plan_version,route_domain,route_reason,route_confidence,solver_profile,"
                           "evaluator_profile,route_required_capabilities,route_evidence,budget FROM runs WHERE id=?",
                           (other_child, child))
        connection.execute("INSERT INTO tasks(id,run_id,parent_id,title,prompt,state,attempts,result_path,last_error,dependencies,"
                           "acceptance,input_question,input_options,input_answer_path,plan_task_id,orchestration,created_at,updated_at) "
                           "SELECT ?,?,parent_id,title,prompt,state,attempts,result_path,last_error,dependencies,"
                           "acceptance,input_question,input_options,input_answer_path,plan_task_id,orchestration,created_at,updated_at FROM tasks WHERE id=?",
                           (other_task, other_child, task))
    other_intent = {**intent, "evolution_run_id": other_child, "task_id": other_task}
    store.record_materialization_launch_intent(parent, other_child, other_task, other_intent)
    other_receipt = {**receipt, "evolution_run_id": other_child, "task_id": other_task,
                     "launch_intent_sha256": hashlib.sha256(encoded(other_intent)).hexdigest()}
    other = store, parent, other_child, other_task, other_intent, execution, other_receipt
    reject_without_changes(other)
    other_receipt["nonce"] = "b" * 32
    prepare(other)
    assert recorded(other)


def test_concurrent_same_receipt_is_one_idempotent_batch(attested: Any) -> None:
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(prepare, attested) for _ in range(4)]
        for future in futures:
            future.result()
    assert status(attested) == "prepared"
    events = [row for row in attested[0].list_events(attested[2]) if row["type"] == "materialization_execution_attested"]
    assert len(events) == 1


def test_concurrent_distinct_receipts_only_one_wins(attested: Any) -> None:
    other = (*attested[:-1], {**copy.deepcopy(attested[-1]), "nonce": "b" * 32})
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(prepare, value) for value in (attested, other)]
        successes = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except ValueError as exc:
                assert str(exc) == "materialization_execution_ledger_mismatch"
    assert successes == 1
    events = [row for row in attested[0].list_events(attested[2]) if row["type"] == "materialization_execution_attested"]
    assert len(events) == 1


def test_receipt_fragment_is_modern_execution_evidence(attested: Any) -> None:
    prepare(attested)
    with attested[0]._connect() as connection:
        connection.execute("DELETE FROM events WHERE id=?", (ids(attested[:-1])["prepared"],))
        connection.execute("UPDATE events SET type='drifted',run_id=? WHERE id=?", (attested[1], event_id(attested)))
    assert attested[0].has_materialization_execution(*attested[1:3])
    assert attested[0].has_materialization_execution_attestation(*attested[1:3])
    reject_without_changes(attested)


@pytest.mark.parametrize("drift", [None, "missing_receipt", "digest", "nonce", "prepared_binding"])
def test_delivery_requires_complete_attested_execution(attested: Any, drift: str | None) -> None:
    store, parent, child, task, intent, execution, receipt = attested
    prepare(attested)
    commit(attested)
    result = {
        "schema_version": "1", "status": "succeeded", "parent_run_id": parent, "evolution_run_id": child,
        **{key: intent[key] for key in ("contract_sha256", "candidate_id", "candidate_path", "candidate_sha256", "attempt_path")},
        "execution": {"status": execution["status"], "exit_code": execution["exit_code"],
                      "duration_ms": execution["duration_ms"], "evidence_path": receipt["execution_path"]},
        "validation": {"passed": True, "evidence": [], "reason": "verified", "details": {}},
        "outputs": [], "error": None,
    }
    plan = {
        "schema_version": "1", "parent_run_id": parent, "evolution_run_id": child, "task_id": task,
        "launch_intent_sha256": receipt["launch_intent_sha256"], "execution_journal_sha256": JOURNAL,
        "execution_sha256": receipt["execution_sha256"], "result": result, "outputs": [],
    }
    assert not store.materialization_delivery_recorded(*attested[1:-1], plan)
    store.record_materialization_delivery(*attested[1:-1], plan)
    assert store.materialization_delivery_recorded(*attested[1:-1], plan)
    if drift is None:
        return
    with store._connect() as connection:
        if drift == "missing_receipt":
            connection.execute("DELETE FROM events WHERE id=?", (event_id(attested),))
        elif drift == "prepared_binding":
            row = connection.execute("SELECT payload FROM events WHERE id=?", (ids(attested[:-1])["prepared"],)).fetchone()
            payload = json.loads(row["payload"])
            del payload["attestation_sha256"]
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), ids(attested[:-1])["prepared"]))
        else:
            row = connection.execute("SELECT payload FROM events WHERE id=?", (event_id(attested),)).fetchone()
            payload = json.loads(row["payload"])
            payload["receipt_sha256" if drift == "digest" else "nonce"] = "f" * 64
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), event_id(attested)))
    before = snapshot(store)
    for method in (store.materialization_delivery_recorded, store.record_materialization_delivery):
        with pytest.raises(ValueError, match="^materialization_delivery_ledger_mismatch$"):
            method(*attested[1:-1], plan)
    assert snapshot(store) == before


@pytest.mark.parametrize("payload", [{}, {"nonce": None}, {"nonce": 42}, {"nonce": "too-short"}, {"nonce": "a" * 31 + "/"}])
@pytest.mark.parametrize("stage", ["absent", "prepared"])
@pytest.mark.parametrize("reserved", [False, True])
def test_unrelated_unknown_nonce_blocks_only_attestation(
    attested: Any, payload: dict, stage: str, reserved: bool,
) -> None:
    store, parent, _, _, _, _, _ = attested
    if stage == "prepared":
        prepare(attested)
    with store._connect() as connection:
        store._append_event(
            connection, parent, None, "drifted" if reserved else "materialization_execution_attested", payload,
            "event-materialization-execution-attested-" + "f" * 64 if reserved else "unrelated-attestation",
        )
    reject_without_changes(attested)
    if stage == "absent":
        assert store.materialization_execution_status(*attested[1:-1], journal_sha256=JOURNAL) == "absent"
        store.prepare_materialization_execution(*attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=100_000)
        store.commit_materialization_execution(*attested[1:-1], journal_sha256=JOURNAL, max_artifact_bytes=100_000)
        assert store.materialization_execution_status(*attested[1:-1], journal_sha256=JOURNAL) == "committed"
