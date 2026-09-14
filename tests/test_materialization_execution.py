"""Recover explicitly prepared execution registration without repeating candidate work."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_evolved_output_materialization import (
    _contract,
    _counted_materialization_source,
    _evolution_fixture,
)
from test_materialization_launch import (
    _assert_no_terminal_claim,
    _attempt,
    _intent,
    _materialize,
)
from test_materialization_launch_durability import _descriptor_names_path
from test_materialization_publication import (
    SimulatedCrash,
    _database_snapshot,
    _filesystem_snapshot,
    _forbid_execution_and_promotion,
)

import famou.controller as controller_module
import famou.materialization_execution as publication
from famou.evolution import CandidateExecution, CommandCandidateRunner, EvolutionError
from famou.materialization_execution import MaterializationExecutionUncertain

PREPARED = "materialization_execution_prepared"
COMMITTED = "materialization_execution_committed"
EXECUTED = "evolved_candidate_executed"


def _fixture(tmp_path: Path, outcome: str = "success"):
    source = _counted_materialization_source(output=outcome == "success")
    if outcome == "failed":
        source += "raise SystemExit(7)\n"
    elif outcome == "timed_out":
        source += "import time\ntime.sleep(10)\n"
    return _evolution_fixture(
        tmp_path, source,
        filename="candidate.txt" if outcome == "preexecution_failed" else "candidate.py",
    )


def _directory(child) -> Path:
    return Path(child.workspace) / "evolution/materialization/.execution-publication"


def _identity(child) -> dict:
    value = json.loads(_intent(child).read_bytes())
    return {key: item for key, item in value.items() if key not in {"runner_sha256", "timeout_seconds"}}


def _execution_events(controller, child, event_type: str):
    return [event for event in controller.store.list_events(child.id) if event["type"] == event_type]


def _execution_rows(controller, child):
    return [row for row in controller.store.list_artifacts(child.id) if row["kind"] == "evolved_candidate_execution"]


def _assert_registered_once(controller, child, result, outcome: str = "success") -> None:
    execution_path = _attempt(child, result) / "execution.json"
    value = json.loads(execution_path.read_bytes())
    assert value["status"] == ("succeeded" if outcome == "success" else outcome)
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"
    rows = _execution_rows(controller, child)
    assert len(rows) == 1
    assert len(_execution_events(controller, child, PREPARED)) == 1
    assert len(_execution_events(controller, child, COMMITTED)) == 1
    executed = _execution_events(controller, child, EXECUTED)
    assert len(executed) == 1
    assert executed[0]["payload"]["status"] == value["status"]
    recorded = [
        event for event in controller.store.list_events(child.id)
        if event["type"] == "artifact_recorded" and event["payload"].get("path") == rows[0]["path"]
    ]
    assert len(recorded) == 1
    assert recorded[0]["payload"]["artifact_id"] == rows[0]["id"]


def _interrupt(monkeypatch, controller, parent, child, result, boundary: str) -> None:
    with monkeypatch.context() as patch:
        if boundary in {"prepared", "committed"}:
            method = "prepare_materialization_execution" if boundary == "prepared" else "commit_materialization_execution"
            original = getattr(controller.store, method)

            def operation_then_crash(*args, **kwargs):
                original(*args, **kwargs)
                raise SimulatedCrash(f"execution registration stopped after {boundary}")

            patch.setattr(controller.store, method, operation_then_crash)
        else:
            original = os.link

            def completion_link_then_crash(source, destination, *args, **kwargs):
                original(source, destination, *args, **kwargs)
                if Path(destination) == _directory(child) / "completed.json":
                    raise SimulatedCrash("execution completion linked before directory sync")

            patch.setattr(os, "link", completion_link_then_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    assert (_directory(child) / "journal.json").is_file()
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"
    _assert_no_terminal_claim(controller, parent, child)


def _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result) -> None:
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)
    for _ in range(2):
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
        assert _database_snapshot(controller, parent, child) == ledger
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"


def _recover_registration_only(monkeypatch, controller, parent, child, result, outcome: str = "success") -> None:
    execution = (_attempt(child, result) / "execution.json").read_bytes()
    _forbid_execution_and_promotion(monkeypatch, controller)
    for _ in range(2):
        with pytest.raises(EvolutionError):
            _materialize(controller, parent, child, result)
        _assert_registered_once(controller, child, result, outcome)
        assert (_directory(child) / "completed.json").is_file()
        assert (_attempt(child, result) / "execution.json").read_bytes() == execution
        _assert_no_terminal_claim(controller, parent, child)
        assert not (Path(parent.workspace) / "output/routes.csv").exists()


def _delete_execution_batch(controller, child) -> None:
    rows = _execution_rows(controller, child)
    paths = {row["path"] for row in rows}
    events = [
        event for event in controller.store.list_events(child.id)
        if event["type"] in {COMMITTED, EXECUTED}
        or event["type"] == "artifact_recorded" and event["payload"].get("path") in paths
    ]
    with controller.store._connect() as connection:
        for row in rows:
            connection.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
        for event in events:
            connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))


@pytest.mark.parametrize("outcome", ["success", "failed", "timed_out"])
@pytest.mark.parametrize("boundary", ["prepared", "committed", "completion_link"])
def test_execution_registration_recovers_without_repeating_or_finalizing_candidate(
    tmp_path: Path, monkeypatch, outcome: str, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome)
    _interrupt(monkeypatch, controller, parent, child, result, boundary)
    assert len(_execution_rows(controller, child)) == int(boundary != "prepared")
    _recover_registration_only(monkeypatch, controller, parent, child, result, outcome)


@pytest.mark.parametrize("outcome", ["success", "failed", "timed_out"])
def test_completed_materialization_replays_modern_execution_without_current_timeout_dependency(
    tmp_path: Path, monkeypatch, outcome: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome)
    expected = _materialize(controller, parent, child, result)
    assert expected["status"] == ("succeeded" if outcome == "success" else "failed")
    _assert_registered_once(controller, child, result, outcome)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _forbid_execution_and_promotion(monkeypatch, controller)
    assert _materialize(controller, parent, child, result, timeout=7) == expected
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_preexecution_failure_creates_no_execution_preparation(tmp_path: Path) -> None:
    controller, parent, child, result = _fixture(tmp_path, "preexecution_failed")
    payload = _materialize(controller, parent, child, result)
    assert payload["status"] == "failed"
    assert payload["execution"]["evidence_path"] is None
    assert not _directory(child).exists()
    assert not _execution_events(controller, child, PREPARED)
    assert not _execution_events(controller, child, COMMITTED)
    assert not _execution_rows(controller, child)


@pytest.mark.parametrize("drift", ["returned_value", "file_bytes", "temporary_evidence"])
def test_runner_return_must_match_exact_execution_file_before_preparation(
    tmp_path: Path, monkeypatch, drift: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = CommandCandidateRunner.run

    def mismatched_runner(self, candidate, workspace, **kwargs):
        execution = original(self, candidate, workspace, **kwargs)
        if drift == "returned_value":
            return replace(execution, duration_ms=execution.duration_ms + 1)
        if drift == "file_bytes":
            value = execution.to_dict()
            value["duration_ms"] += 1
            (workspace / "execution.json").write_text(json.dumps(value), encoding="utf-8")
        else:
            (workspace / ".execution.json.tmp").write_bytes((workspace / "execution.json").read_bytes())
        return execution

    with monkeypatch.context() as patch:
        patch.setattr(CommandCandidateRunner, "run", mismatched_runner)
        with pytest.raises(MaterializationExecutionUncertain):
            _materialize(controller, parent, child, result)
    assert not _directory(child).exists()
    assert not _execution_events(controller, child, PREPARED)
    _assert_no_terminal_claim(controller, parent, child)
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)


def test_raw_execution_file_cannot_create_preparation_on_resume(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)

    def stop_before_preparation(*args, **kwargs):
        raise SimulatedCrash("runner returned but controller has not prepared execution")

    with monkeypatch.context() as patch:
        patch.setattr(controller_module, "publish_materialization_execution", stop_before_preparation)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    assert (_attempt(child, result) / "execution.json").is_file()
    assert not _directory(child).exists()
    identity = _identity(child)
    assert publication.recover_materialization_execution(controller.store, parent, child, identity) is None
    assert publication.inspect_materialization_execution(controller.store, parent, child, identity) is None
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)
    _assert_no_terminal_claim(controller, parent, child)


@pytest.mark.parametrize("fragment", ["filesystem_only", "database_only"])
def test_execution_preparation_fragments_do_not_authorize_registration(
    tmp_path: Path, monkeypatch, fragment: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "prepared")
    if fragment == "filesystem_only":
        with controller.store._connect() as connection:
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, PREPARED))
    else:
        shutil.rmtree(_directory(child))
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)
    assert not _execution_rows(controller, child)
    _assert_no_terminal_claim(controller, parent, child)


@pytest.mark.parametrize("failure", ["artifact", "artifact_event", "execution_event", "commit_event"])
def test_execution_sql_failure_rolls_back_the_whole_batch_then_recovers(
    tmp_path: Path, monkeypatch, failure: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    if failure == "artifact":
        table, condition = "artifacts", "NEW.kind = 'evolved_candidate_execution'"
    elif failure == "artifact_event":
        table, condition = "events", "NEW.type = 'artifact_recorded' AND json_extract(NEW.payload, '$.path') LIKE '%/execution.json'"
    else:
        table = "events"
        condition = "NEW.type = '" + (EXECUTED if failure == "execution_event" else COMMITTED) + "'"
    with controller.store._connect() as connection:
        connection.execute(
            f"CREATE TRIGGER fail_execution BEFORE INSERT ON {table} WHEN {condition} "
            "BEGIN SELECT RAISE(ABORT, 'injected execution registration failure'); END"
        )
    with pytest.raises(MaterializationExecutionUncertain):
        _materialize(controller, parent, child, result)
    assert len(_execution_events(controller, child, PREPARED)) == 1
    assert not _execution_rows(controller, child)
    assert not _execution_events(controller, child, EXECUTED)
    assert not _execution_events(controller, child, COMMITTED)
    _assert_no_terminal_claim(controller, parent, child)
    with controller.store._connect() as connection:
        connection.execute("DROP TRIGGER fail_execution")
    _recover_registration_only(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("boundary", ["prepare", "commit"])
def test_execution_postcommit_exception_is_confirmed_and_keeps_original_outcome(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    method = boundary + "_materialization_execution"
    original = getattr(controller.store, method)

    def committed_then_raise(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected exception after durable transaction")

    monkeypatch.setattr(controller.store, method, committed_then_raise)
    expected = _materialize(controller, parent, child, result)
    assert expected["status"] == "succeeded"
    _assert_registered_once(controller, child, result)
    _forbid_execution_and_promotion(monkeypatch, controller)
    assert _materialize(controller, parent, child, result) == expected


@pytest.mark.parametrize("committed", [False, True])
def test_execution_unknown_commit_never_creates_false_terminal_failure(
    tmp_path: Path, monkeypatch, committed: bool,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_commit = controller.store.commit_materialization_execution
    original_status = controller.store.materialization_execution_status
    failed = False

    def uncertain_commit(*args, **kwargs):
        nonlocal failed
        if committed:
            original_commit(*args, **kwargs)
        failed = True
        raise OSError("commit return unavailable")

    def unqueryable(*args, **kwargs):
        if failed:
            raise sqlite3.OperationalError("database snapshot unavailable")
        return original_status(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_materialization_execution", uncertain_commit)
        patch.setattr(controller.store, "materialization_execution_status", unqueryable)
        with pytest.raises(MaterializationExecutionUncertain):
            _materialize(controller, parent, child, result)
    assert failed
    _assert_no_terminal_claim(controller, parent, child)
    _recover_registration_only(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("missing", ["artifact", "artifact_event", "execution_event", "committed_event", "whole_batch"])
def test_completed_execution_with_deleted_evidence_is_never_rebuilt(
    tmp_path: Path, monkeypatch, missing: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "completion_link")
    assert (_directory(child) / "completed.json").is_file()
    if missing == "whole_batch":
        _delete_execution_batch(controller, child)
    else:
        row = _execution_rows(controller, child)[0]
        with controller.store._connect() as connection:
            if missing == "artifact":
                connection.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
            else:
                event_type = {"artifact_event": "artifact_recorded", "execution_event": EXECUTED, "committed_event": COMMITTED}[missing]
                events = _execution_events(controller, child, event_type)
                event = next(item for item in events if event_type != "artifact_recorded" or item["payload"].get("path") == row["path"])
                connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)
    _assert_no_terminal_claim(controller, parent, child)


@pytest.mark.parametrize("completion", ["absent", "temporary"])
def test_intact_committed_execution_can_finish_only_its_missing_completion(
    tmp_path: Path, monkeypatch, completion: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "completion_link")
    directory = _directory(child)
    completed = directory / "completed.json"
    temporary = directory / ".completed.json.tmp"
    if temporary.exists():
        temporary.unlink()
    if completion == "temporary":
        completed.rename(temporary)
    else:
        completed.unlink()
    ledger = _database_snapshot(controller, parent, child)
    _recover_registration_only(monkeypatch, controller, parent, child, result)
    assert _database_snapshot(controller, parent, child) == ledger


def test_temporary_completion_prevents_reconstruction_of_deleted_batch(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "completion_link")
    directory = _directory(child)
    temporary = directory / ".completed.json.tmp"
    if temporary.exists():
        temporary.unlink()
    (directory / "completed.json").rename(temporary)
    _delete_execution_batch(controller, child)
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("downstream", ["output_journal", "output_event", "terminal_journal", "terminal_marker", "terminal_event"])
def test_downstream_evidence_forbids_rebuilding_a_wholly_missing_execution_batch(
    tmp_path: Path, monkeypatch, downstream: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "committed")
    _delete_execution_batch(controller, child)
    materialization = _directory(child).parent
    if downstream == "output_journal":
        import hashlib

        suffix = hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
        directory = Path(parent.workspace) / ".evolved-output-publications" / suffix
        directory.mkdir(parents=True)
        (directory / "journal.json").write_text("{}", encoding="utf-8")
    elif downstream == "terminal_journal":
        directory = materialization / ".terminal-publication"
        directory.mkdir()
        (directory / "journal.json").write_text("{}", encoding="utf-8")
    elif downstream == "terminal_marker":
        (materialization / "result.json").write_text("{}", encoding="utf-8")
    else:
        controller.store.append_event(
            parent.id,
            "evolved_outputs_promoted" if downstream == "output_event" else "evolved_candidate_materialized",
            {"evolution_run_id": child.id},
        )
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)
    assert not _execution_rows(controller, child)


@pytest.mark.parametrize("drift", ["source", "launch_file", "launch_event", "execution_bytes", "execution_missing", "execution_inode", "journal_identity", "duplicate_execution_event", "execution_owner"])
@pytest.mark.parametrize("boundary", ["prepared", "completion_link"])
def test_execution_authority_and_content_drift_are_preserved_without_repair(
    tmp_path: Path, monkeypatch, drift: str, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, boundary)
    attempt = _attempt(child, result)
    if drift == "source":
        (attempt / "candidate.py").write_text("# changed candidate", encoding="utf-8")
    elif drift == "launch_file":
        _intent(child).unlink()
    elif drift == "launch_event":
        with controller.store._connect() as connection:
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'materialization_launch_intended'", (child.id,))
    elif drift == "execution_bytes":
        (attempt / "execution.json").write_text("{}", encoding="utf-8")
    elif drift == "execution_missing":
        (attempt / "execution.json").unlink()
    elif drift == "execution_inode":
        path = attempt / "execution.json"
        temporary = attempt / "replacement.json"
        temporary.write_bytes(path.read_bytes())
        temporary.replace(path)
    elif drift == "journal_identity":
        path = _directory(child) / "journal.json"
        value = json.loads(path.read_bytes())
        value["task_id"] = "different-task"
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    elif drift == "duplicate_execution_event":
        if boundary == "prepared":
            controller.store.append_event(child.id, EXECUTED, {"candidate_id": result.best_candidate_id})
        else:
            event = _execution_events(controller, child, EXECUTED)[0]
            controller.store.append_event(child.id, EXECUTED, event["payload"], task_id=event["task_id"])
    else:
        if boundary == "prepared":
            event = _execution_events(controller, child, PREPARED)[0]
        else:
            event = _execution_events(controller, child, EXECUTED)[0]
        with controller.store._connect() as connection:
            connection.execute("UPDATE events SET task_id = NULL WHERE id = ?", (event["id"],))
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("node", ["directory", "symlink", "broken_symlink", "fifo", "duplicate_key", "nonfinite", "partial"])
@pytest.mark.parametrize("name", ["journal.json", ".journal.json.tmp", "completed.json", ".completed.json.tmp"])
def test_execution_receipt_unsafe_nodes_and_malformed_bytes_are_preserved(
    tmp_path: Path, monkeypatch, node: str, name: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "prepared")
    path = _directory(child) / name
    if path.exists():
        path.unlink()
    if node == "directory":
        path.mkdir()
    elif node in {"symlink", "broken_symlink"}:
        target = tmp_path / "unrelated-receipt"
        if node == "symlink":
            target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
    elif node == "fifo":
        os.mkfifo(path)
    else:
        content = {"duplicate_key": '{"schema_version":"1","schema_version":"1"}', "nonfinite": '{"value":NaN}', "partial": '{"unfinished":'}[node]
        path.write_text(content, encoding="utf-8")
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)
    assert not _execution_rows(controller, child)


@pytest.mark.parametrize("fault", ["execution_file", "execution_directory", "journal_file", "journal_directory", "completion_partial_write", "completion_directory"])
def test_execution_durability_failure_preserves_evidence_and_never_relaunches(
    tmp_path: Path, monkeypatch, fault: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_publish = controller_module.publish_materialization_execution
    original_sync, original_write = os.fsync, os.write
    injected = 0

    def faulty_publish(*args, **kwargs):
        def sync(descriptor):
            nonlocal injected
            directory = _directory(child)
            targets = {
                "execution_file": _attempt(child, result) / "execution.json",
                "execution_directory": _attempt(child, result),
                "journal_file": directory / ".journal.json.tmp",
                "journal_directory": directory,
                "completion_directory": directory,
            }
            target = targets.get(fault)
            if target is not None and _descriptor_names_path(descriptor, target):
                if fault == "completion_directory" and not (directory / "completed.json").exists():
                    return original_sync(descriptor)
                if fault == "journal_directory" and not (directory / "journal.json").exists():
                    return original_sync(descriptor)
                injected += 1
                raise OSError("injected execution durability fault")
            return original_sync(descriptor)

        def write(descriptor, content):
            nonlocal injected
            if fault == "completion_partial_write" and _descriptor_names_path(descriptor, _directory(child) / ".completed.json.tmp"):
                injected += 1
                if injected == 1:
                    return original_write(descriptor, content[:7])
                raise OSError("partial completion receipt write")
            return original_write(descriptor, content)

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", sync)
            patch.setattr(os, "write", write)
            return original_publish(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(controller_module, "publish_materialization_execution", faulty_publish)
        with pytest.raises(MaterializationExecutionUncertain):
            _materialize(controller, parent, child, result)
    assert injected > 0
    _assert_no_terminal_claim(controller, parent, child)
    if fault == "completion_directory":
        _recover_registration_only(monkeypatch, controller, parent, child, result)
    else:
        _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)


@pytest.mark.parametrize("boundary", ["prepared", "committed"])
def test_native_controller_exit_keeps_one_execution_and_recovers_only_registration(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    program = r'''
import json
import os
import sys
from pathlib import Path
from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import StrategyResult
from famou.runtime import MockRuntime

home, parent_id, child_id, raw_contract, raw_result, boundary = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
method = "prepare_materialization_execution" if boundary == "prepared" else "commit_materialization_execution"
original = getattr(controller.store, method)
def interrupted(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(91)
setattr(controller.store, method, interrupted)
controller.materialize_evolved_outputs(
    parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)),
    StrategyResult(**json.loads(raw_result)), timeout_seconds=1,
)
raise AssertionError("execution interruption hook was not reached")
'''
    completed = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "home"), parent.id, child.id,
         json.dumps(_contract().to_dict()), json.dumps(result.to_dict()), boundary],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert completed.returncode == 91, completed.stderr
    assert (_directory(child) / "journal.json").is_file()
    _recover_registration_only(monkeypatch, controller, parent, child, result)


def test_read_only_execution_inspection_does_not_finish_prepared_registration(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "prepared")
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    with pytest.raises(MaterializationExecutionUncertain):
        publication.inspect_materialization_execution(controller.store, parent, child, _identity(child))
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_missing_execution_journal_cannot_downgrade_completed_modern_cache(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    shutil.rmtree(_directory(child))
    _assert_resume_refuses_without_writes(monkeypatch, controller, parent, child, result)


def test_completed_execution_inspection_returns_exact_result_without_mutation(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _materialize(controller, parent, child, result)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    expected = CandidateExecution.from_dict(json.loads((_attempt(child, result) / "execution.json").read_bytes()))
    assert publication.inspect_materialization_execution(controller.store, parent, child, _identity(child)) == expected
    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger
