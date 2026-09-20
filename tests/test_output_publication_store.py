"""Atomic output ledger publication and exact, read-only replay."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from famou.store import Store

JOURNAL_SHA256 = "a" * 64
CHILD = "evolution-child"


@pytest.fixture
def publication(tmp_path: Path) -> tuple[Store, str, str, list[dict[str, Any]]]:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("publish two outputs", tmp_path / "parent", tasks=[
        {"id": "solver", "title": "Solve", "prompt": "solve"},
        {"id": "prior", "title": "Prior", "prompt": "prior"},
    ])
    outputs = []
    for index, content in enumerate((b"first", b"second")):
        path = f"output/result-{index}.txt"
        outputs.append({
            "artifact_id": "artifact-output-publication-" + hashlib.sha256(
                f"{run.id}\0{CHILD}\0{path}".encode()
            ).hexdigest(),
            "path": path, "format": "text", "fields": [], "required": True,
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        })
    return store, run.id, "solver", outputs


def commit(publication: tuple[Store, str, str, list[dict[str, Any]]], **kwargs: Any) -> None:
    store, run_id, task_id, outputs = publication
    store.commit_output_publication(
        run_id, task_id, CHILD, outputs, journal_sha256=JOURNAL_SHA256,
        max_artifact_bytes=kwargs.pop("max_artifact_bytes", 100), **kwargs,
    )


def committed(publication: tuple[Store, str, str, list[dict[str, Any]]], **kwargs: Any) -> bool:
    store, run_id, task_id, outputs = publication
    return store.output_publication_committed(
        run_id, CHILD, outputs, owner_task_id=task_id,
        journal_sha256=kwargs.pop("journal_sha256", JOURNAL_SHA256), **kwargs,
    )


def snapshot(store: Store, run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return store.list_artifacts(run_id), store.list_events(run_id)


def test_atomic_commit_and_exact_replay(publication: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, run_id, task_id, outputs = publication
    assert not committed(publication)
    traces = []
    original_connect = store._connect

    def connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    commit(publication)
    assert "PRAGMA synchronous = FULL" in traces
    assert "BEGIN IMMEDIATE" in traces
    assert committed(publication)
    before = snapshot(store, run_id)
    assert len(before[0]) == 2
    assert all(item["task_id"] == task_id and item["kind"] == "output" for item in before[0])
    promotion = [event for event in before[1] if event["type"] == "evolved_outputs_promoted"]
    acknowledgement = [event for event in before[1] if event["type"] == "output_publication_committed"]
    assert len(promotion) == len(acknowledgement) == 1
    assert promotion[0]["payload"] == {"evolution_run_id": CHILD, "outputs": outputs}
    assert acknowledgement[0]["payload"] == {"evolution_run_id": CHILD, "journal_sha256": JOURNAL_SHA256}
    commit(publication)
    assert snapshot(store, run_id) == before
    assert not Path(store.get_run(run_id).workspace).exists()


def test_reuses_matching_row_owned_by_another_parent_task(publication: Any) -> None:
    store, run_id, _task_id, outputs = publication
    first = outputs[0]
    first["artifact_id"] = store.add_artifact(
        run_id, "prior", first["path"], first["sha256"], first["size"], "output",
    )
    existing = store.list_artifacts(run_id)[0]
    assert not committed(publication)
    commit(publication, max_artifact_bytes=sum(item["size"] for item in outputs))
    assert committed(publication)
    assert next(item for item in store.list_artifacts(run_id) if item["id"] == existing["id"]) == existing
    assert len([event for event in store.list_events(run_id) if event["type"] == "artifact_recorded"]) == 2


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_lifecycle_terminal_parent_rejects_new_output_commit(publication: Any, status: str) -> None:
    store, run_id, _task_id, _outputs = publication
    store.append_event(run_id, "evolution_requested", {
        "bundle_mode": "compiled", "automatic_lifecycle_version": 1,
    })
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    before = snapshot(store, run_id)
    with pytest.raises(ValueError, match="^output_publication_parent_terminal$"):
        commit(publication)
    assert snapshot(store, run_id) == before


@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("lifecycle", [False, True])
def test_terminal_parent_keeps_exact_committed_replay_read_only(publication: Any, status: str, lifecycle: bool) -> None:
    store, run_id, _task_id, _outputs = publication
    if lifecycle:
        store.append_event(run_id, "evolution_requested", {
            "bundle_mode": "compiled", "automatic_lifecycle_version": 1,
        })
    commit(publication)
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    before = snapshot(store, run_id)
    commit(publication)
    assert snapshot(store, run_id) == before


@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("policy", [
    None,
    {"bundle_mode": "compiled"},
    {"bundle_mode": "single", "automatic_lifecycle_version": 1},
])
def test_legacy_terminal_parent_keeps_publication_compatibility(
    publication: Any, status: str, policy: dict[str, Any] | None,
) -> None:
    store, run_id, _task_id, outputs = publication
    if policy is not None:
        store.append_event(run_id, "evolution_requested", policy)
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    commit(publication)
    assert committed(publication)
    assert len(store.list_artifacts(run_id)) == len(outputs)
    assert store.get_run(run_id).status.value == status


def test_second_artifact_insert_failure_rolls_back_every_row_and_event(publication: Any) -> None:
    store, run_id, _task_id, outputs = publication
    with store._connect() as connection:
        connection.execute(
            "CREATE TRIGGER fail_second_output BEFORE INSERT ON artifacts "
            "WHEN NEW.path = 'output/result-1.txt' BEGIN SELECT RAISE(ABORT, 'private path'); END"
        )
    before = snapshot(store, run_id)
    with pytest.raises(ValueError, match="^output_publication_commit_failed$"):
        commit(publication)
    assert snapshot(store, run_id) == before
    assert not committed(publication)
    with store._connect() as connection:
        connection.execute("DROP TRIGGER fail_second_output")
    commit(publication)
    assert committed(publication)
    assert len(store.list_artifacts(run_id)) == len(outputs)


@pytest.mark.parametrize("event_type", ["artifact_recorded", "evolved_outputs_promoted", "output_publication_committed"])
@pytest.mark.parametrize("fault", ["raise", "return_false"])
def test_event_failure_rolls_back_complete_batch(
    publication: Any, monkeypatch: pytest.MonkeyPatch, event_type: str, fault: str,
) -> None:
    store, run_id, _task_id, _outputs = publication
    original = store._append_event

    def append(connection: Any, run: str, task: str, kind: str, payload: Any, event_id: str | None = None) -> bool:
        if kind == event_type:
            if fault == "raise":
                raise RuntimeError("private storage diagnostic")
            return False
        return original(connection, run, task, kind, payload, event_id)

    monkeypatch.setattr(store, "_append_event", append)
    before = snapshot(store, run_id)
    code = "commit_failed" if fault == "raise" else "ledger_mismatch"
    with pytest.raises(ValueError, match=f"^output_publication_{code}$"):
        commit(publication)
    assert snapshot(store, run_id) == before
    assert not committed(publication)


def test_budget_counts_all_existing_artifacts_and_only_missing_outputs(publication: Any) -> None:
    store, run_id, _task_id, outputs = publication
    store.add_artifact(run_id, "prior", "prompt.txt", "b" * 64, 90, "prompt")
    before = snapshot(store, run_id)
    with pytest.raises(ValueError, match="^output_publication_budget_exceeded$"):
        commit(publication, max_artifact_bytes=100)
    assert snapshot(store, run_id) == before
    commit(publication, max_artifact_bytes=90 + sum(item["size"] for item in outputs))
    assert committed(publication)


@pytest.mark.parametrize("owner", ["missing", "other_run", "different_parent_task"])
def test_invalid_owner_cannot_commit_or_replay(publication: Any, owner: str) -> None:
    store, run_id, _task_id, outputs = publication
    if owner == "other_run":
        other = store.create_run("other")
        wrong_task = store.list_tasks(other.id)[0].id
    elif owner == "different_parent_task":
        commit(publication)
        wrong_task = "prior"
    else:
        wrong_task = "missing"
    before = snapshot(store, run_id)
    with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
        commit((store, run_id, wrong_task, outputs))
    assert snapshot(store, run_id) == before


@pytest.mark.parametrize("conflict", ["duplicate_path", "different_digest", "foreign_id", "partial_reserved_id"])
def test_precommit_conflicts_are_rejected_read_only(publication: Any, conflict: str) -> None:
    store, run_id, task_id, outputs = publication
    first = outputs[0]
    if conflict == "foreign_id":
        other = store.create_run("other")
        owner = store.list_tasks(other.id)[0].id
        first["artifact_id"] = store.add_artifact(other.id, owner, first["path"], first["sha256"], first["size"], "output")
    else:
        existing_id = store.add_artifact(run_id, task_id, first["path"], first["sha256"], first["size"], "output")
        if conflict == "partial_reserved_id":
            with store._connect() as connection:
                connection.execute("UPDATE artifacts SET id = ? WHERE id = ?", (first["artifact_id"], existing_id))
        else:
            first["artifact_id"] = existing_id
            if conflict == "duplicate_path":
                store.add_artifact(run_id, task_id, first["path"], first["sha256"], first["size"], "output")
            else:
                first["sha256"] = "c" * 64
    before = snapshot(store, run_id)
    for operation in (committed, commit):
        with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store, run_id) == before


@pytest.mark.parametrize("drift", [
    "missing_artifact", "missing_artifact_event", "missing_promotion", "missing_commit",
    "missing_both_commit_events", "duplicate_artifact_event",
    "artifact_hash", "artifact_owner", "promotion_task", "commit_hash", "extra_event",
    "duplicate_row", "duplicate_json_key", "nonfinite", "boolean_size",
])
def test_committed_drift_is_never_repaired(publication: Any, drift: str) -> None:
    store, run_id, task_id, outputs = publication
    commit(publication)
    with store._connect() as connection:
        if drift == "missing_artifact":
            connection.execute("DELETE FROM artifacts WHERE id = ?", (outputs[0]["artifact_id"],))
        elif drift == "missing_artifact_event":
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'artifact_recorded'", (run_id,))
        elif drift == "missing_both_commit_events":
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND type IN ('evolved_outputs_promoted', 'output_publication_committed')",
                (run_id,),
            )
        elif drift == "duplicate_artifact_event":
            store._append_event(
                connection, run_id, task_id, "artifact_recorded",
                {key: outputs[0][key] for key in ("artifact_id", "path", "sha256", "size")},
            )
        elif drift in {"missing_promotion", "missing_commit"}:
            kind = "evolved_outputs_promoted" if drift == "missing_promotion" else "output_publication_committed"
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (run_id, kind))
        elif drift in {"artifact_hash", "artifact_owner"}:
            column, value = ("sha256", "d" * 64) if drift == "artifact_hash" else ("task_id", "prior")
            connection.execute(f"UPDATE artifacts SET {column} = ? WHERE id = ?", (value, outputs[0]["artifact_id"]))
        elif drift == "promotion_task":
            connection.execute("UPDATE events SET task_id = 'prior' WHERE run_id = ? AND type = 'evolved_outputs_promoted'", (run_id,))
        elif drift == "duplicate_row":
            connection.execute(
                "INSERT INTO artifacts SELECT 'duplicate', run_id, task_id, path, sha256, size, kind, created_at FROM artifacts WHERE id = ?",
                (outputs[0]["artifact_id"],),
            )
        elif drift == "extra_event":
            store._append_event(connection, run_id, task_id, "evolved_outputs_promoted", {"evolution_run_id": CHILD, "outputs": outputs})
        else:
            if drift == "commit_hash":
                raw = json.dumps({"evolution_run_id": CHILD, "journal_sha256": "e" * 64})
            elif drift == "duplicate_json_key":
                raw = '{"evolution_run_id":"wrong","evolution_run_id":"evolution-child","journal_sha256":"' + JOURNAL_SHA256 + '"}'
            elif drift == "nonfinite":
                raw = '{"evolution_run_id":"evolution-child","journal_sha256":1e999}'
            else:
                changed = json.loads(json.dumps(outputs))
                changed[0]["size"] = True
                raw = json.dumps({"evolution_run_id": CHILD, "outputs": changed})
            kind = "evolved_outputs_promoted" if drift == "boolean_size" else "output_publication_committed"
            connection.execute("UPDATE events SET payload = ? WHERE run_id = ? AND type = ?", (raw, run_id, kind))
    # Raw SQL keeps the snapshot usable even when event JSON is deliberately corrupt.
    with store._connect() as connection:
        before = tuple(connection.iterdump())
    for operation in (committed, commit):
        with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
            operation(publication)
    with store._connect() as connection:
        assert tuple(connection.iterdump()) == before


def test_wrong_journal_digest_cannot_replay(publication: Any) -> None:
    commit(publication)
    with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
        committed(publication, journal_sha256="b" * 64)


@pytest.mark.parametrize("invalid", ["empty", "extra_key", "duplicate_id", "duplicate_path", "unsafe_path", "bool_size", "nan_size", "oversize", "invalid_fields"])
def test_invalid_manifest_is_rejected_before_writes(publication: Any, invalid: str) -> None:
    store, run_id, _task_id, outputs = publication
    before = snapshot(store, run_id)
    if invalid == "empty":
        outputs.clear()
    elif invalid == "extra_key":
        outputs[0]["unexpected"] = True
    elif invalid == "duplicate_id":
        outputs[1]["artifact_id"] = outputs[0]["artifact_id"]
    elif invalid == "duplicate_path":
        outputs[1]["path"] = outputs[0]["path"]
    elif invalid == "unsafe_path":
        outputs[0]["path"] = "output/../secret"
    elif invalid == "invalid_fields":
        outputs[0]["fields"] = ["unexpected-text-field"]
    else:
        outputs[0]["size"] = {"bool_size": True, "nan_size": float("nan"), "oversize": 256 * 1024 + 1}[invalid]
    for operation in (committed, commit):
        with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store, run_id) == before


def test_missing_database_is_not_created_by_commit_probe(tmp_path: Path) -> None:
    store = Store(tmp_path / "absent" / "state.db")
    outputs = [{
        "artifact_id": "artifact-output-publication-" + hashlib.sha256(
            f"parent\0{CHILD}\0output/file.txt".encode()
        ).hexdigest(),
        "path": "output/file.txt", "format": "text", "fields": [], "required": True,
        "size": 0, "sha256": hashlib.sha256(b"").hexdigest(),
    }]
    with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
        store.output_publication_committed(
            "parent", CHILD, outputs, owner_task_id="solver", journal_sha256=JOURNAL_SHA256,
        )
    assert not (tmp_path / "absent").exists()


def test_orphan_reserved_artifact_event_cannot_be_treated_as_uncommitted(publication: Any) -> None:
    store, run_id, task_id, outputs = publication
    store.append_event(
        run_id, "artifact_recorded",
        {key: outputs[0][key] for key in ("artifact_id", "path", "sha256", "size")}, task_id,
    )
    before = snapshot(store, run_id)
    for operation in (committed, commit):
        with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
            operation(publication)
    assert snapshot(store, run_id) == before


def test_deterministic_event_id_owned_by_other_run_is_a_conflict(publication: Any) -> None:
    store, run_id, _task_id, outputs = publication
    other = store.create_run("other")
    owner = store.list_tasks(other.id)[0].id
    event_id = "event-evolved-outputs-promoted-" + hashlib.sha256(f"{run_id}\0{CHILD}".encode()).hexdigest()
    store.append_event(other.id, "evolved_outputs_promoted", {"evolution_run_id": CHILD, "outputs": outputs}, owner, event_id)
    before = snapshot(store, run_id), snapshot(store, other.id)
    for operation in (committed, commit):
        with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
            operation(publication)
    assert (snapshot(store, run_id), snapshot(store, other.id)) == before


def test_read_rejects_owner_drift_even_when_all_batch_rows_agree(publication: Any) -> None:
    store, run_id, _task_id, _outputs = publication
    commit(publication)
    with store._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET task_id = 'prior' WHERE run_id = ? AND kind = 'output'",
            (run_id,),
        )
        connection.execute(
            "UPDATE events SET task_id = 'prior' WHERE run_id = ? "
            "AND type IN ('artifact_recorded', 'evolved_outputs_promoted', "
            "'output_publication_committed')",
            (run_id,),
        )
    before = snapshot(store, run_id)

    with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
        committed(publication)

    assert snapshot(store, run_id) == before


def test_has_output_publication_distinguishes_acknowledgement_from_legacy_events(publication: Any) -> None:
    store, run_id, task_id, outputs = publication
    assert not store.has_output_publication(run_id, CHILD)
    legacy_id = "event-evolved-outputs-promoted-" + hashlib.sha256(f"{run_id}\0{CHILD}".encode()).hexdigest()
    store.append_event(
        run_id, "evolved_outputs_promoted", {"evolution_run_id": CHILD, "outputs": outputs},
        task_id, legacy_id,
    )
    assert not store.has_output_publication(run_id, CHILD)
    store.append_event(run_id, "output_publication_committed", {
        "evolution_run_id": "unrelated-child", "journal_sha256": JOURNAL_SHA256,
    }, task_id)
    assert not store.has_output_publication(run_id, CHILD)
    store.append_event(run_id, "output_publication_committed", {
        "evolution_run_id": CHILD, "journal_sha256": JOURNAL_SHA256,
    }, task_id)
    assert store.has_output_publication(run_id, CHILD)


@pytest.mark.parametrize("drift", ["none", "changed_type", "changed_run", "malformed_payload"])
def test_has_output_publication_preserves_evidence_with_reserved_ack_id(publication: Any, drift: str) -> None:
    store, run_id, _task_id, _outputs = publication
    commit(publication)
    event_id = "event-output-publication-committed-" + hashlib.sha256(f"{run_id}\0{CHILD}".encode()).hexdigest()
    if drift == "changed_run":
        other = store.create_run("other")
        with store._connect() as connection:
            connection.execute("UPDATE events SET run_id = ? WHERE id = ?", (other.id, event_id))
    elif drift != "none":
        column, value = ("type", "unrelated") if drift == "changed_type" else ("payload", "invalid JSON")
        with store._connect() as connection:
            connection.execute(f"UPDATE events SET {column} = ? WHERE id = ?", (value, event_id))
    with store._connect() as connection:
        before = tuple(connection.iterdump())
    assert store.has_output_publication(run_id, CHILD)
    with store._connect() as connection:
        assert tuple(connection.iterdump()) == before


@pytest.mark.parametrize("payload", [
    "not JSON", "[]", "{}",
    '{"evolution_run_id":"evolution-child","evolution_run_id":"other","journal_sha256":"' + JOURNAL_SHA256 + '"}',
    '{"evolution_run_id":"evolution-child","journal_sha256":1e999}',
    '{"evolution_run_id":false,"journal_sha256":"' + JOURNAL_SHA256 + '"}',
])
def test_has_output_publication_rejects_unclassifiable_ack_payload(publication: Any, payload: str) -> None:
    store, run_id, task_id, _outputs = publication
    store.append_event(run_id, "output_publication_committed", {}, task_id, "changed-event-id")
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = 'changed-event-id'", (payload,))
        before = tuple(connection.iterdump())
    with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
        store.has_output_publication(run_id, CHILD)
    with store._connect() as connection:
        assert tuple(connection.iterdump()) == before


def test_has_output_publication_reads_only_one_snapshot(publication: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, run_id, _task_id, _outputs = publication
    original_connect = sqlite3.connect
    traces = []
    calls = []

    def connect(database: str, **kwargs: Any) -> sqlite3.Connection:
        calls.append((database, kwargs))
        connection = original_connect(database, **kwargs)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert not store.has_output_publication(run_id, CHILD)
    assert len(calls) == 1 and calls[0][0].endswith("?mode=ro") and calls[0][1]["uri"]
    assert traces[0] == "BEGIN"
    assert sum(statement.startswith("SELECT") for statement in traces) == 1


def test_has_output_publication_does_not_create_missing_database(tmp_path: Path) -> None:
    store = Store(tmp_path / "absent" / "state.db")
    with pytest.raises(ValueError, match="^output_publication_ledger_mismatch$"):
        store.has_output_publication("parent", CHILD)
    assert not (tmp_path / "absent").exists()
