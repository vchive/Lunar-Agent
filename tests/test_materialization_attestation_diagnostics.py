"""Manual execution receipts remain observable and sanitized in diagnostics and exports."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_diagnostic_snapshot import CHILD, PARENT, seed, source_state

from lunar_evolution.diagnostic_snapshot import diagnostic_snapshot
from lunar_evolution.evolution import CandidateExecution
from lunar_evolution.materialization_diagnostics import diagnose_materialization
from lunar_evolution.materialization_evidence_bundle import export_materialization_evidence

KIND = "materialization_execution_attested"
NONCE = "private-attestation-nonce-do-not-export-0123456789"


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


@pytest.fixture
def attested_inventory(tmp_path: Path):
    database = tmp_path / "source" / "state.db"
    database.parent.mkdir()
    seed(database)
    parent, child = database.parent / "parent", database.parent / "child"
    parent.mkdir()
    directory = child / "evolution/materialization/.execution-publication"
    directory.mkdir(parents=True)
    suffix = hashlib.sha256(f"{PARENT}\0{CHILD}".encode()).hexdigest()
    attempt = "evolution/materialization/candidate-1-" + "b" * 12
    execution_path = child / attempt / "execution.json"
    execution_path.parent.mkdir()
    execution = CandidateExecution("succeeded", 0, 10, stdout="private execution log").to_dict()
    execution_path.write_bytes(encoded(execution))
    info = execution_path.stat()
    intent = {
        "schema_version": "1", "parent_run_id": PARENT, "evolution_run_id": CHILD,
        "task_id": "child-task", "contract_sha256": "a" * 64, "strategy": "population",
        "candidate_id": "candidate-1", "candidate_path": "evolution/archive/candidate-1/candidate.py",
        "candidate_sha256": "b" * 64, "attempt_path": attempt, "runner_sha256": "c" * 64,
        "timeout_seconds": 10,
    }
    (directory.parent / "launch-intent.json").write_bytes(encoded(intent))
    receipt = {
        "schema_version": "1", "parent_run_id": PARENT, "evolution_run_id": CHILD,
        "task_id": "child-task", "launch_intent_sha256": digest(intent),
        "candidate_id": "candidate-1", "candidate_sha256": "b" * 64, "attempt_path": attempt,
        "execution_path": attempt + "/execution.json", "execution_sha256": digest(execution),
        "execution_size": len(encoded(execution)), "device": info.st_dev, "inode": info.st_ino, "nonce": NONCE,
    }
    journal = {
        "schema_version": "1", "parent_run_id": PARENT, "evolution_run_id": CHILD,
        "task_id": "child-task", "launch_intent_sha256": digest(intent),
        "execution_path": receipt["execution_path"], "execution_sha256": receipt["execution_sha256"],
        "execution_size": receipt["execution_size"], "artifact_id": "artifact-materialization-execution-" + suffix,
        "device": info.st_dev, "inode": info.st_ino, "attestation": receipt,
    }
    (directory / "journal.json").write_bytes(encoded(journal))
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("DELETE FROM events")
        connection.execute("DELETE FROM artifacts")
        for identity, kind, payload in (
            ("event-materialization-launch-intended-" + suffix, "materialization_launch_intended", {
                "parent_run_id": PARENT, "evolution_run_id": CHILD, "intent_sha256": digest(intent),
            }),
            ("event-materialization-execution-prepared-" + suffix, "materialization_execution_prepared", {
                "parent_run_id": PARENT, "evolution_run_id": CHILD, "owner_task_id": "child-task",
                "journal_sha256": digest(journal), "attestation_sha256": digest(receipt),
            }),
            ("event-materialization-execution-attested-" + suffix, KIND, {
                **receipt, "receipt_sha256": digest(receipt), "journal_sha256": digest(journal),
            }),
        ):
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (identity, CHILD, "child-task", kind, json.dumps(payload)))
    return database, directory, journal, suffix


def report(fixture):
    database = fixture[0]
    before = source_state(database)
    value = diagnose_materialization(database, PARENT, CHILD)
    assert source_state(database) == before
    assert value["recovery_eligibility"] == "not_assessed"
    assert NONCE not in json.dumps(value)
    assert "private execution log" not in json.dumps(value)
    return value


def test_attested_preparation_is_observed_without_becoming_recovery_authority(attested_inventory) -> None:
    value = report(attested_inventory)
    stage = value["stages"]["execution"]
    assert value["status"] == "attention_required"
    assert stage["events"][KIND] == 1
    assert stage["files"]["journal"]["state"] == "present"
    assert not any("attestation" in issue or "mismatch" in issue for issue in stage["issues"])
    assert "registration_not_observed" in stage["issues"]


@pytest.mark.parametrize("drift", ["missing_event", "missing_receipt", "malformed_receipt", "nonce", "digest", "journal_digest", "owner", "duplicate", "foreign_reserved"])
def test_attestation_fragments_and_receipt_drift_remain_visible(attested_inventory, drift: str) -> None:
    database, directory, journal, suffix = attested_inventory
    identity = "event-materialization-execution-attested-" + suffix
    with closing(sqlite3.connect(database)) as connection, connection:
        if drift == "missing_event":
            connection.execute("DELETE FROM events WHERE id=?", (identity,))
        elif drift in {"missing_receipt", "malformed_receipt"}:
            if drift == "missing_receipt":
                del journal["attestation"]
            else:
                journal["attestation"] = None
            (directory / "journal.json").write_bytes(encoded(journal))
        elif drift == "duplicate":
            connection.execute("INSERT INTO events SELECT 'duplicate',run_id,task_id,type,payload FROM events WHERE id=?", (identity,))
        elif drift == "owner":
            connection.execute("UPDATE events SET task_id='parent-task' WHERE id=?", (identity,))
        elif drift == "foreign_reserved":
            connection.execute("UPDATE events SET run_id='foreign',type='unrelated' WHERE id=?", (identity,))
        else:
            payload = json.loads(connection.execute("SELECT payload FROM events WHERE id=?", (identity,)).fetchone()[0])
            payload[{"nonce": "nonce", "digest": "receipt_sha256", "journal_digest": "journal_sha256"}[drift]] = "f" * 64
            connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), identity))
    value = report(attested_inventory)
    stage = value["stages"]["execution"]
    assert value["status"] == "attention_required"
    assert stage["state"] in {"incomplete", "invalid"}
    assert any("attestation" in issue or issue == "duplicate_receipt" or issue == "receipt_identity_mismatch" for issue in stage["issues"])


def test_snapshot_captures_attestation_reserved_id_with_changed_owner_and_type(attested_inventory) -> None:
    database, _, _, suffix = attested_inventory
    identity = "event-materialization-execution-attested-" + suffix
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("UPDATE events SET run_id='foreign',type='unrelated' WHERE id=?", (identity,))
    before = source_state(database)
    value = diagnostic_snapshot(database, PARENT, CHILD)
    assert any(row["id"] == identity and row["run_id"] == "foreign" for row in value["events"])
    assert source_state(database) == before


@pytest.mark.parametrize("drift", ["missing", "different", "wrong_type"])
def test_preparation_attestation_digest_drift_is_reported_without_writes(attested_inventory, drift: str) -> None:
    database, _, _, suffix = attested_inventory
    identity = "event-materialization-execution-prepared-" + suffix
    with closing(sqlite3.connect(database)) as connection, connection:
        payload = json.loads(connection.execute("SELECT payload FROM events WHERE id=?", (identity,)).fetchone()[0])
        if drift == "missing":
            del payload["attestation_sha256"]
        else:
            payload["attestation_sha256"] = True if drift == "wrong_type" else "f" * 64
        connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), identity))
    value = report(attested_inventory)
    assert value["status"] == "attention_required"
    assert value["stages"]["execution"]["state"] == "invalid"
    assert "attestation_digest_mismatch" in value["stages"]["execution"]["issues"]


def test_larger_attested_journal_is_read_with_the_protocol_bound(attested_inventory) -> None:
    _, directory, journal, _ = attested_inventory
    journal["attestation"]["attempt_path"] = "evolution/materialization/" + "x" * 4096
    (directory / "journal.json").write_bytes(encoded(journal))
    assert 4096 < (directory / "journal.json").stat().st_size < 24 * 1024
    value = report(attested_inventory)
    observed = value["stages"]["execution"]["files"]["journal"]
    assert observed["state"] == "present" and observed.get("issue") != "record_size_limit"
    (directory / "journal.json").write_bytes(b" " * (24 * 1024 + 1))
    value = report(attested_inventory)
    assert value["stages"]["execution"]["files"]["journal"]["issue"] == "record_size_limit"


def test_evidence_bundle_includes_only_attestation_envelope_and_preserves_sources(attested_inventory, tmp_path) -> None:
    database, _, _, suffix = attested_inventory
    destination = tmp_path / "export.json"
    before = source_state(database)
    outcome = export_materialization_evidence(database, PARENT, CHILD, destination)
    assert outcome["status"] == "exported"
    bundle = json.loads(destination.read_bytes())
    attested = [row for row in bundle["events"] if row["id"] == "event-materialization-execution-attested-" + suffix]
    assert len(attested) == 1 and attested[0]["type"] == KIND
    assert set(attested[0]) == {"id", "run_id", "task_id", "type", "payload_size", "payload_sha256"}
    assert bundle["report"]["stages"]["execution"]["events"][KIND] == 1
    assert all(secret not in destination.read_text() for secret in (NONCE, "private execution log", str(database.parent)))
    assert source_state(database) == before
