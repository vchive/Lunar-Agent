"""Recover only explicitly prepared terminal results; never repair completed drift."""

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_evolved_output_materialization import (
    _contract,
    _counted_materialization_source,
    _evolution_fixture,
)

import lunar_evolution.materialization_publication as publication
from lunar_evolution.evolution import CommandCandidateRunner, EvolutionError

RESULT_RELATIVE = "evolution/materialization/result.json"
PREPARED_EVENT = "materialization_publication_prepared"
COMMITTED_EVENT = "materialization_publication_committed"
TERMINAL_EVENT = "evolved_candidate_materialized"


class SimulatedCrash(BaseException):
    """Stop the operation without ordinary exception compensation."""


def _fixture(tmp_path: Path, outcome: str = "success"):
    source = _counted_materialization_source(output=outcome == "success")
    return _evolution_fixture(
        tmp_path, source, filename="candidate.txt" if outcome == "preexecution_failed" else "candidate.py",
    )


def _materialize(controller, parent, child, result):
    return controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1,
    )


def _directory(child) -> Path:
    return Path(child.workspace) / "evolution/materialization/.terminal-publication"


def _marker(child) -> Path:
    return Path(child.workspace) / RESULT_RELATIVE


def _database_snapshot(controller, parent, child):
    return (
        controller.store.list_artifacts(parent.id), controller.store.list_artifacts(child.id),
        controller.store.list_events(parent.id), controller.store.list_events(child.id),
    )


def _filesystem_snapshot(*roots: Path) -> dict[tuple[int, str], tuple]:
    snapshot = {}
    for index, root in enumerate(roots):
        for path in root.rglob("*"):
            info = path.lstat()
            key = (index, path.relative_to(root).as_posix())
            if stat.S_ISREG(info.st_mode):
                snapshot[key] = ("file", info.st_ino, path.read_bytes())
            elif stat.S_ISLNK(info.st_mode):
                snapshot[key] = ("symlink", os.readlink(path))
            else:
                snapshot[key] = ("node", info.st_mode)
    return snapshot


def _assert_execution_count(child, outcome: str) -> None:
    counters = list(Path(child.workspace).rglob("execution-count.txt"))
    if outcome == "preexecution_failed":
        assert counters == []
    else:
        assert len(counters) == 1
        assert counters[0].read_text(encoding="utf-8") == "1"


def _forbid_execution_and_promotion(monkeypatch, controller) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("terminal recovery reexecuted a candidate or promoted outputs")

    monkeypatch.setattr(CommandCandidateRunner, "run", unexpected)
    monkeypatch.setattr(controller, "_promote_evolved_outputs", unexpected)


def _interrupt(monkeypatch, controller, parent, child, result, boundary: str) -> dict:
    with monkeypatch.context() as patch:
        if boundary in {"prepared", "committed"}:
            method = (
                "prepare_materialization_publication" if boundary == "prepared"
                else "commit_materialization_publication"
            )
            original = getattr(controller.store, method)

            def commit_then_crash(*args, **kwargs):
                original(*args, **kwargs)
                raise SimulatedCrash(f"stopped after {boundary}")

            patch.setattr(controller.store, method, commit_then_crash)
        elif boundary == "marker":
            original = os.link

            def link_then_crash(source, destination, *args, **kwargs):
                original(source, destination, *args, **kwargs)
                if Path(destination) == _marker(child):
                    raise SimulatedCrash("stopped after final marker link")

            patch.setattr(os, "link", link_then_crash)
        else:
            def complete_crash(*args, **kwargs):
                raise SimulatedCrash("stopped before completion receipt")

            patch.setattr(publication, "_write_complete", complete_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    directory = _directory(child)
    assert (directory / "journal.json").is_file()
    assert not (directory / "completed.json").exists()
    assert _marker(child).exists() is (boundary != "prepared")
    return json.loads((directory / "result.blob").read_bytes())


@pytest.mark.parametrize("outcome", ["success", "failed", "preexecution_failed"])
@pytest.mark.parametrize("boundary", ["prepared", "marker", "committed", "completion"])
def test_prepared_terminal_result_recovers_without_candidate_or_output_replay(
    tmp_path: Path, monkeypatch, outcome: str, boundary: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome)
    expected = _interrupt(monkeypatch, controller, parent, child, result, boundary)
    _assert_execution_count(child, outcome)
    _forbid_execution_and_promotion(monkeypatch, controller)

    recovered = _materialize(controller, parent, child, result)

    assert recovered == expected
    assert recovered["status"] == ("succeeded" if outcome == "success" else "failed")
    assert (bool(recovered["outputs"])) is (outcome == "success")
    assert (recovered["execution"]["evidence_path"] is None) is (outcome == "preexecution_failed")
    assert (_directory(child) / "completed.json").is_file()
    assert json.loads(_marker(child).read_bytes()) == expected
    _assert_execution_count(child, outcome)
    rows = controller.store.list_artifacts(child.id)
    assert len([row for row in rows if row["kind"] == "evolved_materialization"]) == 1
    assert len([
        event for event in controller.store.list_events(parent.id)
        if event["type"] == TERMINAL_EVENT
    ]) == 1
    child_events = controller.store.list_events(child.id)
    assert len([event for event in child_events if event["type"] == PREPARED_EVENT]) == 1
    assert len([event for event in child_events if event["type"] == COMMITTED_EVENT]) == 1
    ledger = _database_snapshot(controller, parent, child)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    assert _materialize(controller, parent, child, result) == recovered
    assert _database_snapshot(controller, parent, child) == ledger
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files


@pytest.mark.parametrize("failure", ["artifact", "artifact_event", "parent_event", "commit_event"])
def test_terminal_sql_failure_rolls_back_batch_and_later_recovers(tmp_path: Path, monkeypatch, failure: str) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    if failure == "artifact":
        table, condition = "artifacts", "NEW.kind = 'evolved_materialization'"
    elif failure == "artifact_event":
        table = "events"
        condition = (
            "NEW.type = 'artifact_recorded' AND "
            f"json_extract(NEW.payload, '$.path') = '{RESULT_RELATIVE}'"
        )
    else:
        table = "events"
        kind = TERMINAL_EVENT if failure == "parent_event" else COMMITTED_EVENT
        condition = f"NEW.type = '{kind}'"
    with controller.store._connect() as connection:
        connection.execute(
            f"CREATE TRIGGER fail_terminal BEFORE INSERT ON {table} WHEN {condition} "
            "BEGIN SELECT RAISE(ABORT, 'injected terminal write failure'); END"
        )
    with pytest.raises(EvolutionError):
        _materialize(controller, parent, child, result)

    assert _marker(child).is_file()
    assert not (_directory(child) / "completed.json").exists()
    assert not any(
        row["kind"] == "evolved_materialization"
        for row in controller.store.list_artifacts(child.id)
    )
    assert not any(
        event["type"] == TERMINAL_EVENT for event in controller.store.list_events(parent.id)
    )
    events = controller.store.list_events(child.id)
    assert len([event for event in events if event["type"] == PREPARED_EVENT]) == 1
    assert not any(event["type"] == COMMITTED_EVENT for event in events)
    assert not any(
        event["type"] == "artifact_recorded" and event["payload"].get("path") == RESULT_RELATIVE
        for event in events
    )
    with controller.store._connect() as connection:
        connection.execute("DROP TRIGGER fail_terminal")
    _forbid_execution_and_promotion(monkeypatch, controller)
    assert _materialize(controller, parent, child, result)["status"] == "succeeded"
    _assert_execution_count(child, "success")


def test_preparation_failure_leaves_no_marker_and_does_not_authorize_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)

    def reject_preparation(*args, **kwargs):
        raise ValueError("materialization_publication_prepare_failed")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "prepare_materialization_publication", reject_preparation)
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
    assert not _marker(child).exists()
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)

    with pytest.raises(EvolutionError):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_committed_exception_is_confirmed_without_rewriting_result(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = controller.store.commit_materialization_publication

    def commit_then_exception(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("commit acknowledgement unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_materialization_publication", commit_then_exception)
        payload = _materialize(controller, parent, child, result)

    assert payload["status"] == "succeeded"
    assert (_directory(child) / "completed.json").is_file()
    assert json.loads(_marker(child).read_bytes()) == payload
    _assert_execution_count(child, "success")


@pytest.mark.parametrize("committed", [False, True], ids=["before_commit", "after_commit"])
def test_unqueryable_commit_preserves_evidence_until_status_can_be_confirmed(
    tmp_path: Path, monkeypatch, committed: bool
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = controller.store.commit_materialization_publication
    with monkeypatch.context() as patch:
        def unavailable(*args, **kwargs):
            raise sqlite3.OperationalError("database temporarily unavailable")

        def commit_without_acknowledgement(*args, **kwargs):
            if committed:
                original(*args, **kwargs)
            patch.setattr(controller.store, "materialization_publication_status", unavailable)
            raise sqlite3.OperationalError("commit outcome unknown")

        patch.setattr(controller.store, "commit_materialization_publication", commit_without_acknowledgement)
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)

    assert _marker(child).is_file()
    assert not (_directory(child) / "completed.json").exists()
    expected = json.loads(_marker(child).read_bytes())
    assert expected["status"] == "succeeded"
    _forbid_execution_and_promotion(monkeypatch, controller)
    assert _materialize(controller, parent, child, result) == expected
    _assert_execution_count(child, "success")


@pytest.mark.parametrize("drift", [
    "marker", "artifact", "artifact_event", "parent_event", "prepared_event", "commit_event",
    "journal", "stage", "private_directory", "terminal_batch",
])
def test_completed_result_with_missing_evidence_is_never_repaired(
    tmp_path: Path, monkeypatch, drift: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    if drift in {"marker", "journal", "stage"}:
        target = {
            "marker": _marker(child), "journal": _directory(child) / "journal.json",
            "stage": _directory(child) / "result.blob",
        }[drift]
        target.unlink()
    elif drift == "private_directory":
        shutil.rmtree(_directory(child))
    else:
        with controller.store._connect() as connection:
            if drift == "terminal_batch":
                connection.execute(
                    "DELETE FROM artifacts WHERE run_id = ? AND kind = 'evolved_materialization'",
                    (child.id,),
                )
                connection.execute(
                    "DELETE FROM events WHERE run_id = ? AND type = 'artifact_recorded' "
                    "AND json_extract(payload, '$.path') = ?", (child.id, RESULT_RELATIVE),
                )
                connection.execute(
                    "DELETE FROM events WHERE (run_id = ? AND type = ?) OR (run_id = ? AND type = ?)",
                    (parent.id, TERMINAL_EVENT, child.id, COMMITTED_EVENT),
                )
            elif drift == "artifact":
                connection.execute(
                    "DELETE FROM artifacts WHERE run_id = ? AND kind = 'evolved_materialization'",
                    (child.id,),
                )
            elif drift == "artifact_event":
                connection.execute(
                    "DELETE FROM events WHERE run_id = ? AND type = 'artifact_recorded' "
                    "AND json_extract(payload, '$.path') = ?", (child.id, RESULT_RELATIVE),
                )
            else:
                event_type = {
                    "parent_event": TERMINAL_EVENT, "prepared_event": PREPARED_EVENT,
                    "commit_event": COMMITTED_EVENT,
                }[drift]
                run_id = parent.id if drift == "parent_event" else child.id
                connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (run_id, event_type))
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)

    with pytest.raises(EvolutionError):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_missing_completion_receipt_can_finalize_only_an_intact_committed_result(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    expected = _materialize(controller, parent, child, result)
    (_directory(child) / "completed.json").unlink()
    ledger = _database_snapshot(controller, parent, child)
    marker_inode = _marker(child).stat().st_ino
    _forbid_execution_and_promotion(monkeypatch, controller)

    assert _materialize(controller, parent, child, result) == expected

    assert (_directory(child) / "completed.json").is_file()
    assert _marker(child).stat().st_ino == marker_inode
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("drift", ["execution", "execution_ledger", "output", "candidate", "marker_conflict"])
def test_prepared_result_rejects_changed_authority_without_any_repair(
    tmp_path: Path, monkeypatch, drift: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    expected = _interrupt(monkeypatch, controller, parent, child, result, "prepared")
    if drift == "execution":
        path = Path(child.workspace) / expected["execution"]["evidence_path"]
        path.write_text("{}", encoding="utf-8")
    elif drift == "execution_ledger":
        with controller.store._connect() as connection:
            connection.execute(
                "DELETE FROM artifacts WHERE run_id = ? AND kind = 'evolved_candidate_execution'",
                (child.id,),
            )
    elif drift == "output":
        (Path(parent.workspace) / expected["outputs"][0]["path"]).write_bytes(b"external drift\n")
    elif drift == "candidate":
        (Path(child.workspace) / result.best_candidate_path).write_text("raise SystemExit(9)\n")
    else:
        _marker(child).write_bytes(b"an unrelated existing marker\n")
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)

    with pytest.raises(EvolutionError):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("node", ["symlink", "broken_symlink", "directory", "fifo", "duplicate_json"])
def test_prepared_journal_abnormal_nodes_are_preserved(tmp_path: Path, monkeypatch, node: str) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "prepared")
    journal = _directory(child) / "journal.json"
    raw = journal.read_bytes()
    journal.unlink()
    if node == "symlink":
        outside = tmp_path / "outside-journal.json"
        outside.write_bytes(raw)
        journal.symlink_to(outside)
    elif node == "broken_symlink":
        journal.symlink_to(tmp_path / "missing-journal.json")
    elif node == "directory":
        journal.mkdir()
    elif node == "fifo":
        os.mkfifo(journal)
    else:
        journal.write_text('{"schema_version":"1","schema_version":"1"}')
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)

    with pytest.raises(EvolutionError):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("outcome", ["success", "failed"])
def test_complete_legacy_result_remains_a_read_only_replay(tmp_path: Path, monkeypatch, outcome: str) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome)
    expected = _materialize(controller, parent, child, result)
    artifact = next(
        row for row in controller.store.list_artifacts(child.id)
        if row["kind"] == "evolved_materialization"
    )
    legacy_id = "artifact-legacy-materialization"
    with controller.store._connect() as connection:
        connection.execute("UPDATE artifacts SET id = ? WHERE id = ?", (legacy_id, artifact["id"]))
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND type IN (?, ?)",
            (child.id, PREPARED_EVENT, COMMITTED_EVENT),
        )
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND type = 'artifact_recorded' "
            "AND json_extract(payload, '$.path') = ?", (child.id, RESULT_RELATIVE),
        )
        controller.store._append_event(
            connection, child.id, artifact["task_id"], "artifact_recorded",
            {"artifact_id": legacy_id, "path": RESULT_RELATIVE,
             "sha256": artifact["sha256"], "size": artifact["size"]},
        )
    shutil.rmtree(_directory(child))
    # Strip the entire newer delivery protocol when constructing a legacy terminal fixture.
    shutil.rmtree(Path(child.workspace) / "evolution/materialization/.delivery-publication")
    with controller.store._connect() as connection:
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND type = 'materialization_delivery_prepared'", (child.id,),
        )
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)

    def unexpected_write(*args, **kwargs):
        pytest.fail("legacy result replay created modern preparation or terminal rows")

    monkeypatch.setattr(controller.store, "prepare_materialization_publication", unexpected_write)
    monkeypatch.setattr(controller.store, "commit_materialization_publication", unexpected_write)
    assert _materialize(controller, parent, child, result) == expected
    assert _database_snapshot(controller, parent, child) == ledger
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files


@pytest.mark.parametrize("boundary", ["prepared", "marker", "committed"])
def test_native_process_exit_leaves_terminal_publication_recoverable(
    tmp_path: Path, monkeypatch, boundary: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    script = r'''
import json
import os
import sys
from pathlib import Path
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import StrategyResult
from lunar_evolution.runtime import MockRuntime

home, parent_id, child_id, raw_result, raw_contract, boundary = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
child = controller.store.get_run(child_id)
assert child is not None
if boundary == "marker":
    original = os.link
    def interrupted(source, destination, *args, **kwargs):
        original(source, destination, *args, **kwargs)
        if Path(destination) == Path(child.workspace) / "evolution/materialization/result.json":
            os._exit(79)
    os.link = interrupted
else:
    method = "prepare_materialization_publication" if boundary == "prepared" else "commit_materialization_publication"
    original = getattr(controller.store, method)
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(79)
    setattr(controller.store, method, interrupted)
controller.materialize_evolved_outputs(
    parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)),
    StrategyResult(**json.loads(raw_result)), timeout_seconds=1,
)
raise AssertionError("process interruption was not reached")
'''
    process = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "home"), parent.id, child.id,
         json.dumps(result.to_dict()), json.dumps(_contract().to_dict()), boundary],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert process.returncode == 79, process.stderr
    expected = json.loads((_directory(child) / "result.blob").read_bytes())
    _assert_execution_count(child, "success")
    _forbid_execution_and_promotion(monkeypatch, controller)

    assert _materialize(controller, parent, child, result) == expected
    assert (_directory(child) / "completed.json").is_file()
    _assert_execution_count(child, "success")


def test_preparation_commit_exception_is_confirmed_before_marker_publication(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = controller.store.prepare_materialization_publication

    def prepare_then_exception(*args, **kwargs):
        original(*args, **kwargs)
        assert not _marker(child).exists()
        raise sqlite3.OperationalError("preparation acknowledgement unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "prepare_materialization_publication", prepare_then_exception)
        payload = _materialize(controller, parent, child, result)

    assert payload["status"] == "succeeded"
    assert (_directory(child) / "completed.json").is_file()
    _assert_execution_count(child, "success")


@pytest.mark.parametrize("batch", ["intact", "deleted"])
def test_temporary_completion_receipt_proves_commit_and_forbids_batch_recreation(
    tmp_path: Path, monkeypatch, batch: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    complete = _directory(child) / "completed.json"
    temporary = _directory(child) / ".completed.json.tmp"
    original_link = os.link

    def interrupt_before_completion_link(source, destination, *args, **kwargs):
        if Path(destination) == complete:
            assert temporary.is_file()
            raise SimulatedCrash("stopped after completion temporary file was persisted")
        return original_link(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupt_before_completion_link)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    assert temporary.is_file()
    assert not complete.exists()
    expected = json.loads(_marker(child).read_bytes())
    if batch == "deleted":
        with controller.store._connect() as connection:
            connection.execute(
                "DELETE FROM artifacts WHERE run_id = ? AND kind = 'evolved_materialization'",
                (child.id,),
            )
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND type = 'artifact_recorded' "
                "AND json_extract(payload, '$.path') = ?", (child.id, RESULT_RELATIVE),
            )
            connection.execute(
                "DELETE FROM events WHERE (run_id = ? AND type = ?) OR (run_id = ? AND type = ?)",
                (parent.id, TERMINAL_EVENT, child.id, COMMITTED_EVENT),
            )
    ledger = _database_snapshot(controller, parent, child)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    marker_inode = _marker(child).stat().st_ino
    _forbid_execution_and_promotion(monkeypatch, controller)
    if batch == "intact":
        assert _materialize(controller, parent, child, result) == expected
        assert complete.is_file()
        assert _marker(child).stat().st_ino == marker_inode
    else:
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger
    _assert_execution_count(child, "success")


def test_completion_directory_sync_failure_is_finished_before_replay_returns(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    directory = _directory(child)
    complete = directory / "completed.json"
    original_sync = publication._sync

    def fail_after_completion_link(path):
        if Path(path) == directory and complete.exists():
            raise OSError("injected directory sync failure after completion link")
        return original_sync(path)

    with monkeypatch.context() as patch:
        patch.setattr(publication, "_sync", fail_after_completion_link)
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
    assert complete.is_file()
    expected = json.loads(_marker(child).read_bytes())
    ledger = _database_snapshot(controller, parent, child)
    complete_identity = (complete.stat().st_dev, complete.stat().st_ino)
    directory_identity = (directory.stat().st_dev, directory.stat().st_ino)
    synchronized = []
    original_fsync = os.fsync

    def observe_sync(descriptor):
        info = os.fstat(descriptor)
        synchronized.append((info.st_dev, info.st_ino))
        original_fsync(descriptor)

    _forbid_execution_and_promotion(monkeypatch, controller)
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", observe_sync)
        assert _materialize(controller, parent, child, result) == expected

    assert complete_identity in synchronized
    assert directory_identity in synchronized
    assert _database_snapshot(controller, parent, child) == ledger
    _assert_execution_count(child, "success")
