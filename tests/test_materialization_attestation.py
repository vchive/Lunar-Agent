"""Explicit operator receipts register exact offline fixture evidence without rerunning it."""

import gc
import hashlib
import json
import os
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from test_materialization_execution import _assert_registered_once, _directory, _fixture, _identity
from test_materialization_launch import _assert_no_terminal_claim, _attempt, _intent, _materialize
from test_materialization_publication import (
    SimulatedCrash,
    _database_snapshot,
    _filesystem_snapshot,
    _forbid_execution_and_promotion,
)

import lunar_evolution.controller as controller_module
import lunar_evolution.materialization_attestation as attestation
import lunar_evolution.materialization_execution as publication
from lunar_evolution import cli
from lunar_evolution.evolution import EvolutionError
from lunar_evolution.materialization_launch import materialization_lock

ATTESTED = "materialization_execution_attested"


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _receipt(child, nonce="operator-confirmation-000000000001"):
    intent = json.loads(_intent(child).read_bytes())
    path = Path(child.workspace) / intent["attempt_path"] / "execution.json"
    content, info = path.read_bytes(), path.stat()
    return {
        "schema_version": "1",
        **{key: intent[key] for key in ("parent_run_id", "evolution_run_id", "task_id", "candidate_id", "candidate_sha256", "attempt_path")},
        "launch_intent_sha256": hashlib.sha256(_intent(child).read_bytes()).hexdigest(),
        "execution_path": intent["attempt_path"] + "/execution.json",
        "execution_sha256": hashlib.sha256(content).hexdigest(), "execution_size": len(content),
        "device": info.st_dev, "inode": info.st_ino, "nonce": nonce,
    }


def _raw(tmp_path, monkeypatch, *, forbid=True, outcome="success"):
    controller, parent, child, result = _fixture(tmp_path, outcome)
    def stop(*args, **kwargs):
        raise SimulatedCrash("fixture runner returned before 091 publication")
    with monkeypatch.context() as patch:
        patch.setattr(controller_module, "publish_materialization_execution", stop)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(_encode(_receipt(child)))
    assert not _directory(child).exists()
    if forbid:
        _forbid_execution_and_promotion(monkeypatch, controller)
    return controller, parent, child, result, receipt


def _call(fixture):
    controller, parent, child, _, receipt = fixture
    return attestation.attest_materialization_execution(controller.store, parent, child, receipt)


def _refuses(fixture):
    controller, parent, child, _, _ = fixture
    ledger = _database_snapshot(controller, parent, child)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    with pytest.raises(EvolutionError, match="^materialization_attestation_invalid$"):
        _call(fixture)
    assert _database_snapshot(controller, parent, child) == ledger
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files


def test_correct_receipt_registers_and_replays_without_execution_or_promotion(tmp_path, monkeypatch):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, result, receipt = fixture
    original = (_attempt(child, result) / "execution.json").read_bytes()
    assert _call(fixture).status == "succeeded"
    _assert_registered_once(controller, child, result)
    events = [event for event in controller.store.list_events(child.id) if event["type"] == ATTESTED]
    assert len(events) == 1
    assert events[0]["payload"]["receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert json.loads((_directory(child) / "journal.json").read_bytes())["attestation"] == _receipt(child)
    ledger = _database_snapshot(controller, parent, child)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    assert _call(fixture).status == "succeeded"
    assert _database_snapshot(controller, parent, child) == ledger
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert (_attempt(child, result) / "execution.json").read_bytes() == original
    _assert_no_terminal_claim(controller, parent, child)


@pytest.mark.parametrize("key,value", [
    ("schema_version", 1), ("nonce", "too-short"), ("nonce", "x" * 129), ("nonce", None),
    ("parent_run_id", []), ("task_id", True), ("candidate_id", "../candidate"),
    ("launch_intent_sha256", 123), ("execution_sha256", None), ("candidate_sha256", "G" * 64),
    ("execution_size", True), ("execution_size", -1), ("execution_size", 65537),
    ("device", "0"), ("inode", True), ("attempt_path", "../attempt"),
    ("execution_path", "/private/execution.json"),
])
def test_receipt_schema_rejects_invalid_values(tmp_path, key, value):
    receipt = {
        "schema_version": "1", "parent_run_id": "parent", "evolution_run_id": "child", "task_id": "task",
        "candidate_id": "candidate", "candidate_sha256": "a" * 64,
        "attempt_path": "evolution/materialization/candidate-aaaaaaaaaaaa",
        "execution_path": "evolution/materialization/candidate-aaaaaaaaaaaa/execution.json",
        "launch_intent_sha256": "b" * 64, "execution_sha256": "c" * 64,
        "execution_size": 50, "device": 0, "inode": 1, "nonce": "n" * 32,
    }
    receipt[key] = value
    path = tmp_path / "receipt.json"
    path.write_bytes(_encode(receipt))
    with pytest.raises(EvolutionError, match="^materialization_attestation_invalid$"):
        attestation.read_attestation_receipt(path)


@pytest.mark.parametrize("kind", ["missing_key", "extra_key", "duplicate_key", "noncanonical", "nan", "oversized", "symlink", "fifo", "directory", "parent_symlink"])
def test_bad_receipt_does_not_touch_source(tmp_path, monkeypatch, kind):
    fixture = _raw(tmp_path, monkeypatch)
    path = fixture[-1]
    receipt = json.loads(path.read_bytes())
    if kind == "missing_key":
        del receipt["nonce"]
        path.write_bytes(_encode(receipt))
    elif kind == "extra_key":
        path.write_bytes(_encode({**receipt, "private_token": "sk-private-do-not-echo"}))
    elif kind == "duplicate_key":
        path.write_bytes(path.read_bytes().replace(b'"nonce":', b'"nonce": "sk-private-do-not-echo", "nonce":'))
    elif kind == "noncanonical":
        path.write_text(json.dumps(receipt))
    elif kind == "nan":
        path.write_bytes(path.read_bytes().replace(b'"device":', b'"extra": NaN, "device":'))
    elif kind == "oversized":
        path.write_bytes(b"x" * (attestation.MAX_ATTESTATION_BYTES + 1))
    elif kind == "parent_symlink":
        directory = tmp_path / "receipts"
        directory.mkdir()
        path.rename(directory / path.name)
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        fixture = (*fixture[:-1], alias / path.name)
    else:
        path.unlink()
        if kind == "symlink":
            path.symlink_to(_intent(fixture[2]))
        elif kind == "fifo":
            os.mkfifo(path)
        else:
            path.mkdir()
    _refuses(fixture)


@pytest.mark.parametrize("key", ["parent_run_id", "evolution_run_id", "task_id", "launch_intent_sha256", "execution_sha256", "execution_size", "device", "inode", "candidate_id", "candidate_sha256"])
def test_exact_receipt_binding_drift_refuses_without_writes(tmp_path, monkeypatch, key):
    fixture = _raw(tmp_path, monkeypatch)
    path = fixture[-1]
    receipt = json.loads(path.read_bytes())
    if key in {"device", "inode", "execution_size"}:
        receipt[key] += 1
    elif key.endswith("sha256"):
        receipt[key] = "0" * 64
    else:
        receipt[key] = "different"
    if key in {"candidate_id", "candidate_sha256"}:
        receipt["attempt_path"] = f"evolution/materialization/{receipt['candidate_id']}-{receipt['candidate_sha256'][:12]}"
        receipt["execution_path"] = receipt["attempt_path"] + "/execution.json"
    path.write_bytes(_encode(receipt))
    _refuses(fixture)


@pytest.mark.parametrize("kind", ["missing", "temporary_only", "temporary_alongside", "replaced_inode", "symlink", "candidate_drift", "launch_drift"])
def test_source_changes_do_not_authorize_registration(tmp_path, monkeypatch, kind):
    fixture = _raw(tmp_path, monkeypatch)
    _, _, child, result, _ = fixture
    execution = _attempt(child, result) / "execution.json"
    if kind in {"missing", "temporary_only"}:
        execution.rename(execution.with_name(".execution.json.tmp") if kind == "temporary_only" else execution.with_name("retained.json"))
    elif kind == "temporary_alongside":
        execution.with_name(".execution.json.tmp").write_bytes(execution.read_bytes())
    elif kind == "replaced_inode":
        replacement = execution.with_name("replacement.json")
        replacement.write_bytes(execution.read_bytes())
        replacement.replace(execution)
    elif kind == "symlink":
        target = execution.with_name("retained.json")
        execution.rename(target)
        execution.symlink_to(target)
    elif kind == "candidate_drift":
        execution.with_name("candidate.py").write_text("# changed\n")
    else:
        _intent(child).write_bytes(b"{}\n")
    _refuses(fixture)


@pytest.mark.parametrize("kind", ["terminal_file", "terminal_directory", "delivery_directory", "output_directory", "terminal_event", "output_event"])
def test_downstream_evidence_refuses_before_registration(tmp_path, monkeypatch, kind):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, _, _ = fixture
    root = _intent(child).parent
    suffix = hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
    if kind == "terminal_file":
        (root / "result.json").write_bytes(b"{}\n")
    elif kind == "terminal_directory":
        (root / ".terminal-publication").mkdir()
    elif kind == "delivery_directory":
        (root / ".delivery-publication").mkdir()
    elif kind == "output_directory":
        (Path(parent.workspace) / ".evolved-output-publications" / suffix).mkdir(parents=True)
    elif kind == "terminal_event":
        controller.store.append_event(child.id, "materialization_publication_prepared", {})
    else:
        controller.store.append_event(parent.id, "evolved_outputs_promoted", {"evolution_run_id": child.id})
    _refuses(fixture)


@pytest.mark.parametrize("boundary", ["before_prepared", "after_prepared", "after_committed", "before_completion"])
def test_interrupted_attestation_retries_exact_receipt(tmp_path, monkeypatch, boundary):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, result, _ = fixture
    with monkeypatch.context() as patch:
        if boundary == "before_completion":
            def crash(*args):
                raise SimulatedCrash()
            patch.setattr(publication, "_write_complete", crash)
        else:
            name = "commit_materialization_execution" if boundary == "after_committed" else "prepare_materialization_execution"
            original = getattr(controller.store, name)
            def crash(*args, **kwargs):
                if boundary != "before_prepared":
                    original(*args, **kwargs)
                raise SimulatedCrash()
            patch.setattr(controller.store, name, crash)
        with pytest.raises(SimulatedCrash):
            _call(fixture)
    events = [event for event in controller.store.list_events(child.id) if event["type"] == ATTESTED]
    assert len(events) == int(boundary != "before_prepared")
    if boundary == "before_prepared":
        with pytest.raises(EvolutionError):
            publication.recover_materialization_execution(controller.store, parent, child, _identity(child))
    assert _call(fixture).status == "succeeded"
    _assert_registered_once(controller, child, result)
    assert len([event for event in controller.store.list_events(child.id) if event["type"] == ATTESTED]) == 1


def test_prepared_attestation_recovers_through_normal_091_without_receipt_file(tmp_path, monkeypatch):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, result, receipt = fixture
    original = controller.store.prepare_materialization_execution
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedCrash()
    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "prepare_materialization_execution", crash)
        with pytest.raises(SimulatedCrash):
            _call(fixture)
    receipt.unlink()
    recovered = publication.recover_materialization_execution(controller.store, parent, child, _identity(child))
    assert recovered.status == "succeeded"
    _assert_registered_once(controller, child, result)


@pytest.mark.parametrize("damage", ["deleted_attestation", "changed_attestation", "removed_journal_attestation", "different_nonce"])
def test_retained_attestation_cannot_be_downgraded_or_replaced(tmp_path, monkeypatch, damage):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, _, receipt = fixture
    _call(fixture)
    if damage in {"deleted_attestation", "changed_attestation"}:
        with controller.store._connect() as connection:
            if damage == "deleted_attestation":
                connection.execute("DELETE FROM events WHERE type = ?", (ATTESTED,))
            else:
                connection.execute("UPDATE events SET payload = '{}' WHERE type = ?", (ATTESTED,))
    elif damage == "removed_journal_attestation":
        path = _directory(child) / "journal.json"
        value = json.loads(path.read_bytes())
        del value["attestation"]
        path.write_bytes(_encode(value))
    else:
        value = json.loads(receipt.read_bytes())
        value["nonce"] = "a-different-confirmation-0000000001"
        receipt.write_bytes(_encode(value))
    _refuses(fixture)
    if damage != "different_nonce":
        with pytest.raises(EvolutionError):
            publication.recover_materialization_execution(controller.store, parent, child, _identity(child))


@pytest.mark.parametrize("collect_at", [None, "before_validation", "after_validation"])
def test_cli_preflights_and_returns_only_registration_metadata(tmp_path, monkeypatch, capsys, collect_at):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, result, receipt = fixture
    original_snapshot = attestation._snapshot_store
    collections = []

    @contextmanager
    def collect_during_preflight(database):
        with original_snapshot(database) as copied:
            if collect_at == "before_validation":
                collections.append(gc.collect())
            yield copied
            if collect_at == "after_validation":
                collections.append(gc.collect())

    monkeypatch.setattr(attestation, "_snapshot_store", collect_during_preflight)
    def forbidden(*args, **kwargs):
        pytest.fail("CLI initialized normal configuration or controller")
    monkeypatch.setattr(cli, "_config", forbidden)
    args = ["attest-materialization-execution", parent.id, child.id, "--receipt", str(receipt), "--home", str(controller.config.home), "--json"]
    # SQLite's transaction context does not close its connection. Keep the fixture's
    # WAL alive across both preflights so GC cannot checkpoint the source mid-snapshot.
    # The production snapshot guard remains strict about real source changes.
    with closing(controller.store._connect()):
        for _ in range(2):
            assert cli.main(args) == 0
            payload = json.loads(capsys.readouterr().out)
            assert payload == {"status": "registered", "parent_run_id": parent.id, "evolution_run_id": child.id,
                               "task_id": _identity(child)["task_id"], "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
    assert len(collections) == (0 if collect_at is None else 2)
    _assert_registered_once(controller, child, result)


def test_cli_bad_receipt_and_missing_source_create_no_home(tmp_path, monkeypatch, capsys):
    fixture = _raw(tmp_path, monkeypatch)
    _, parent, child, _, receipt = fixture
    home = tmp_path / "missing-home"
    args = ["attest-materialization-execution", parent.id, child.id, "--receipt", str(receipt), "--home", str(home), "--json"]
    assert cli.main(args) == 2
    assert not home.exists()
    assert "materialization_attestation_invalid" in capsys.readouterr().err
    receipt.write_bytes(b'{"secret": "sk-private"}')
    assert cli.main(args) == 2
    assert not home.exists()
    assert "sk-private" not in capsys.readouterr().err


def test_concurrent_cli_attestation_is_nonblocking_and_does_not_consume_nonce(tmp_path, monkeypatch):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, _, receipt = fixture
    with materialization_lock(child):
        result = subprocess.run([
            sys.executable, "-m", "lunar_evolution", "attest-materialization-execution", parent.id, child.id,
            "--receipt", str(receipt), "--home", str(controller.config.home), "--json",
        ], capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2
    assert "materialization_already_running" in result.stderr
    assert not _directory(child).exists()
    assert not controller.store.has_materialization_execution_attestation(parent.id, child.id)
    assert _call(fixture).status == "succeeded"


@pytest.mark.parametrize("outcome", ["success", "failed"])
def test_attested_registration_enters_normal_delivery_without_running_candidate(tmp_path, monkeypatch, outcome):
    fixture = _raw(tmp_path, monkeypatch, forbid=False, outcome=outcome)
    controller, parent, child, result, _ = fixture
    def forbidden(*args, **kwargs):
        pytest.fail("normal resume reran an attested candidate")
    monkeypatch.setattr(controller_module.CommandCandidateRunner, "run", forbidden)
    _call(fixture)
    delivered = _materialize(controller, parent, child, result)
    assert delivered["status"] == ("succeeded" if outcome == "success" else "failed")
    assert _materialize(controller, parent, child, result) == delivered
    _assert_registered_once(controller, child, result, outcome)
    assert (Path(parent.workspace) / "output/routes.csv").exists() == (outcome == "success")
    # Once 088/089 downstream evidence exists, even the original receipt only permits observation.
    _refuses(fixture)


@pytest.mark.parametrize("boundary", ["before_read", "before_prepare"])
def test_inode_replacement_during_registration_never_consumes_nonce(tmp_path, monkeypatch, boundary):
    fixture = _raw(tmp_path, monkeypatch)
    controller, _, child, result, _ = fixture
    path = _attempt(child, result) / "execution.json"
    if boundary == "before_read":
        original = publication._read
        def drift(target, maximum):
            content = original(target, maximum)
            if target == path:
                replacement = path.with_name("replacement.json")
                replacement.write_bytes(content)
                replacement.replace(path)
            return content
        monkeypatch.setattr(publication, "_read", drift)
    else:
        original = publication._write_record
        def drift(directory, name, content):
            original(directory, name, content)
            if name == "journal.json":
                replacement = path.with_name("replacement.json")
                replacement.write_bytes(path.read_bytes())
                replacement.replace(path)
        monkeypatch.setattr(publication, "_write_record", drift)
    with pytest.raises(EvolutionError, match="^materialization_attestation_invalid$"):
        _call(fixture)
    assert not controller.store.has_materialization_execution_attestation(fixture[1].id, child.id)
    assert not controller.store.has_materialization_execution(fixture[1].id, child.id)


@pytest.mark.parametrize("collect_connections", [False, True])
def test_cli_uses_one_frozen_receipt_for_registration_and_response(
    tmp_path, monkeypatch, capsys, collect_connections,
):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, _, path = fixture
    original_receipt = json.loads(path.read_bytes())
    original_snapshot = attestation._snapshot_store
    @contextmanager
    def replace_after_preflight(database):
        with original_snapshot(database) as copied:
            if collect_connections:
                gc.collect()
            yield copied
        changed = {**original_receipt, "nonce": "another-operator-receipt-000000001"}
        path.write_bytes(_encode(changed))
    monkeypatch.setattr(attestation, "_snapshot_store", replace_after_preflight)
    # Keep this fixture's live WAL open: collecting older connections must not checkpoint
    # the source halfway through a test of receipt immutability. The snapshot guard stays strict.
    with closing(controller.store._connect()):
        assert cli.main(["attest-materialization-execution", parent.id, child.id, "--receipt", str(path), "--home", str(controller.config.home), "--json"]) == 0
    response = json.loads(capsys.readouterr().out)
    stored = next(event for event in controller.store.list_events(child.id) if event["type"] == ATTESTED)["payload"]
    assert stored["nonce"] == original_receipt["nonce"]
    assert stored["receipt_sha256"] == response["receipt_sha256"] == hashlib.sha256(_encode(original_receipt)).hexdigest()


@pytest.mark.parametrize("problem", ["receipt_drift", "missing_execution", "downstream", "wrong_owner"])
def test_cli_rejection_does_not_open_live_store(tmp_path, monkeypatch, capsys, problem):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, result, path = fixture
    if problem == "receipt_drift":
        receipt = json.loads(path.read_bytes())
        receipt["inode"] += 1
        path.write_bytes(_encode(receipt))
    elif problem == "missing_execution":
        (_attempt(child, result) / "execution.json").unlink()
    elif problem == "downstream":
        (_intent(child).parent / ".delivery-publication").mkdir()
    else:
        with controller.store._connect() as connection:
            connection.execute("UPDATE tasks SET run_id = ? WHERE run_id = ?", (parent.id, child.id))
    original = attestation.Store._connect
    def forbid_live(self):
        if self.database == controller.store.database:
            pytest.fail("invalid attestation opened live writable Store")
        return original(self)
    monkeypatch.setattr(attestation.Store, "_connect", forbid_live)
    assert cli.main(["attest-materialization-execution", parent.id, child.id, "--receipt", str(path), "--home", str(controller.config.home), "--json"]) == 2
    assert "materialization_attestation_invalid" in capsys.readouterr().err


@pytest.mark.parametrize("downstream", ["output_ack", "terminal_prepared", "terminal_event"])
def test_committed_attestation_retry_refuses_database_only_downstream(tmp_path, monkeypatch, capsys, downstream):
    fixture = _raw(tmp_path, monkeypatch)
    controller, parent, child, _, receipt = fixture
    _call(fixture)
    if downstream == "terminal_prepared":
        controller.store.append_event(
            child.id, "materialization_publication_prepared", {"evolution_run_id": child.id},
            task_id=_identity(child)["task_id"],
        )
    else:
        kind = "output_publication_committed" if downstream == "output_ack" else "evolved_candidate_materialized"
        controller.store.append_event(parent.id, kind, {"evolution_run_id": child.id})
    materialization = _intent(child).parent
    suffix = hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
    assert not (materialization / ".terminal-publication").exists()
    assert not (materialization / "result.json").exists()
    assert not (Path(parent.workspace) / ".evolved-output-publications" / suffix).exists()
    _refuses(fixture)
    ledger = _database_snapshot(controller, parent, child)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    original = attestation.Store._connect
    def forbid_live(self):
        if self.database == controller.store.database:
            pytest.fail("downstream attestation retry opened live writable Store")
        return original(self)
    with monkeypatch.context() as patch:
        patch.setattr(attestation.Store, "_connect", forbid_live)
        assert cli.main([
            "attest-materialization-execution", parent.id, child.id, "--receipt", str(receipt),
            "--home", str(controller.config.home), "--json",
        ]) == 2
    assert "materialization_attestation_invalid" in capsys.readouterr().err
    assert _database_snapshot(controller, parent, child) == ledger
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    # Ordinary 091 observation still accepts its intact completed execution batch.
    assert publication.recover_materialization_execution(
        controller.store, parent, child, _identity(child),
    ).status == "succeeded"
