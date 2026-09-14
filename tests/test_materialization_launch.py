"""A recorded launch is observation on resume, never authority for a second runner call."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_evolved_output_materialization import (
    _contract,
    _counted_materialization_source,
    _evolution_fixture,
)
from test_materialization_publication import (
    SimulatedCrash,
    _database_snapshot,
    _filesystem_snapshot,
)

import famou.controller as controller_module
import famou.materialization_launch as launch
from famou.evolution import CommandCandidateRunner
from famou.materialization_launch import MaterializationLaunchUncertain

INTENT_RELATIVE = "evolution/materialization/launch-intent.json"
LAUNCH_EVENT = "materialization_launch_intended"


def _fixture(tmp_path: Path, *, outcome: str = "success"):
    return _evolution_fixture(
        tmp_path, _counted_materialization_source(output=outcome == "success"),
        filename="candidate.txt" if outcome == "preexecution_failed" else "candidate.py",
    )


def _materialize(controller, parent, child, result, *, timeout: float = 1):
    return controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=timeout,
    )


def _intent(child) -> Path:
    return Path(child.workspace) / INTENT_RELATIVE


def _marker(child) -> Path:
    return _intent(child).with_name("result.json")


def _attempt(child, result) -> Path:
    source = Path(child.workspace) / result.best_candidate_path
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return _intent(child).parent / f"{result.best_candidate_id}-{digest[:12]}"


def _events(controller, child):
    return [event for event in controller.store.list_events(child.id) if event["type"] == LAUNCH_EVENT]


def _assert_no_terminal_claim(controller, parent, child) -> None:
    assert not _marker(child).exists()
    assert not (_intent(child).parent / ".terminal-publication").exists()
    assert not any(
        row["kind"] == "evolved_materialization"
        for row in controller.store.list_artifacts(child.id)
    )
    assert not any(
        event["type"] == "evolved_candidate_materialized"
        for event in controller.store.list_events(parent.id)
    )


def _deny_runner(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("a retained launch intent authorized a second runner invocation")

    monkeypatch.setattr(CommandCandidateRunner, "run", unexpected)


def _interrupt_after_intent(monkeypatch, controller, parent, child, result) -> None:
    original = launch.prepare_launch_intent

    def prepared_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        assert _intent(child).is_file()
        assert len(_events(controller, child)) == 1
        raise SimulatedCrash("stop after durable intent before entering runner")

    with monkeypatch.context() as patch:
        patch.setattr(launch, "prepare_launch_intent", prepared_then_crash)
        patch.setattr(controller_module, "prepare_launch_intent", prepared_then_crash, raising=False)
        _deny_runner(patch)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)


def test_intent_before_runner_interruption_preserves_attempt_and_never_launches(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt_after_intent(monkeypatch, controller, parent, child, result)
    attempt = _attempt(child, result)
    sentinel = attempt / "retain-uncertain-attempt.txt"
    sentinel.write_text("must never be cleaned", encoding="utf-8")
    assert not (attempt / "execution-count.txt").exists()
    assert not (attempt / "execution.json").exists()
    assert not (attempt / ".execution.json.tmp").exists()
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    for _ in range(2):
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
        assert _database_snapshot(controller, parent, child) == ledger
    _assert_no_terminal_claim(controller, parent, child)


@pytest.mark.parametrize("exception", [OSError, ValueError, RuntimeError])
def test_runner_exception_after_intent_cannot_become_preexecution_failure(
    tmp_path: Path, monkeypatch, exception
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    calls = 0

    def interrupted_runner(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert _intent(child).is_file()
        assert len(_events(controller, child)) == 1
        raise exception("runner stopped without durable execution evidence")

    with monkeypatch.context() as patch:
        patch.setattr(CommandCandidateRunner, "run", interrupted_runner)
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
    assert calls == 1
    _assert_no_terminal_claim(controller, parent, child)
    assert not (_attempt(child, result) / "execution.json").exists()
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    with pytest.raises(MaterializationLaunchUncertain):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("outcome", ["success", "failed"])
def test_completed_launch_replays_without_requiring_the_old_request_timeout(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome=outcome)
    expected = _materialize(controller, parent, child, result)
    assert expected["status"] == ("succeeded" if outcome == "success" else "failed")
    intent = json.loads(_intent(child).read_bytes())
    assert intent["timeout_seconds"] == 1
    assert len(_events(controller, child)) == 1
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    assert _materialize(controller, parent, child, result, timeout=7) == expected

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("corrupt_intent", [False, True], ids=["valid_intent", "missing_intent"])
def test_terminal_preparation_recovers_only_with_intact_launch_evidence(
    tmp_path: Path, monkeypatch, corrupt_intent: bool
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original = controller.store.prepare_materialization_publication

    def terminal_prepared_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedCrash("terminal payload is prepared after candidate execution")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "prepare_materialization_publication", terminal_prepared_then_crash)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    directory = _intent(child).parent / ".terminal-publication"
    expected = json.loads((directory / "result.blob").read_bytes())
    if corrupt_intent:
        _intent(child).unlink()
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)
    if corrupt_intent:
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
        assert _database_snapshot(controller, parent, child) == ledger
        assert not _marker(child).exists()
    else:
        assert _materialize(controller, parent, child, result) == expected
        assert (directory / "completed.json").is_file()
        assert len(_events(controller, child)) == 1
    assert (_attempt(child, result) / "execution-count.txt").read_text() == "1"


@pytest.mark.parametrize("drift", ["intent_missing", "event_missing", "intent_changed", "event_owner", "duplicate_event"])
@pytest.mark.parametrize("completed", [False, True], ids=["uncertain", "completed"])
def test_launch_evidence_fragments_and_drift_are_never_repaired(
    tmp_path: Path, monkeypatch, drift: str, completed: bool
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    if completed:
        _materialize(controller, parent, child, result)
    else:
        _interrupt_after_intent(monkeypatch, controller, parent, child, result)
    event = _events(controller, child)[0]
    if drift == "intent_missing":
        _intent(child).unlink()
    elif drift == "intent_changed":
        value = json.loads(_intent(child).read_bytes())
        value["candidate_sha256"] = "0" * 64
        _intent(child).write_text(json.dumps(value), encoding="utf-8")
    else:
        with controller.store._connect() as connection:
            if drift == "event_missing":
                connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))
            elif drift == "event_owner":
                connection.execute("UPDATE events SET task_id = NULL WHERE id = ?", (event["id"],))
            else:
                controller.store._append_event(
                    connection, child.id, event["task_id"], LAUNCH_EVENT, event["payload"],
                )
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    with pytest.raises(MaterializationLaunchUncertain):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("node", ["symlink", "broken_symlink", "directory", "fifo", "duplicate_json", "nonfinite_json"])
def test_unsafe_launch_nodes_preserve_the_attempt_without_entering_runner(
    tmp_path: Path, monkeypatch, node: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt_after_intent(monkeypatch, controller, parent, child, result)
    intent = _intent(child)
    content = intent.read_bytes()
    intent.unlink()
    if node == "symlink":
        outside = tmp_path / "outside-intent.json"
        outside.write_bytes(content)
        intent.symlink_to(outside)
    elif node == "broken_symlink":
        intent.symlink_to(tmp_path / "missing-intent.json")
    elif node == "directory":
        intent.mkdir()
    elif node == "fifo":
        os.mkfifo(intent)
    elif node == "duplicate_json":
        intent.write_text('{"schema_version":"1","schema_version":"1"}', encoding="utf-8")
    else:
        intent.write_text('{"timeout_seconds":1e999}', encoding="utf-8")
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    with pytest.raises(MaterializationLaunchUncertain):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("fault", ["final_link", "database_record"])
def test_failed_intent_preparation_never_runs_or_creates_failed_terminal_result(
    tmp_path: Path, monkeypatch, fault: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_link = os.link

    def fail_link(source, destination, *args, **kwargs):
        if Path(destination) == _intent(child):
            raise OSError("launch-intent final link failed")
        return original_link(source, destination, *args, **kwargs)

    def fail_record(*args, **kwargs):
        raise sqlite3.OperationalError("launch-intent database record unavailable")

    with monkeypatch.context() as patch:
        _deny_runner(patch)
        if fault == "final_link":
            patch.setattr(os, "link", fail_link)
        else:
            patch.setattr(controller.store, "record_materialization_launch_intent", fail_record)
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
    _assert_no_terminal_claim(controller, parent, child)
    assert _events(controller, child) == []
    assert not (_attempt(child, result) / "execution-count.txt").exists()
    if fault == "final_link":
        assert _intent(child).with_name(".launch-intent.json.tmp").is_file()
    else:
        assert _intent(child).is_file()
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    with pytest.raises(MaterializationLaunchUncertain):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_preexecution_failure_keeps_no_launch_intent_and_replays_normally(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path, outcome="preexecution_failed")
    _deny_runner(monkeypatch)
    expected = _materialize(controller, parent, child, result)
    assert expected["status"] == "failed"
    assert expected["execution"]["evidence_path"] is None
    assert not _intent(child).exists()
    assert not _intent(child).with_name(".launch-intent.json.tmp").exists()
    assert _events(controller, child) == []
    ledger = _database_snapshot(controller, parent, child)
    assert _materialize(controller, parent, child, result) == expected
    assert _database_snapshot(controller, parent, child) == ledger


def test_legacy_complete_result_without_launch_evidence_is_still_read_only(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    expected = _materialize(controller, parent, child, result)
    # Construct the complete pre-090/091/092 format, including a legacy execution artifact ID.
    artifact = next(row for row in controller.store.list_artifacts(child.id) if row["kind"] == "evolved_candidate_execution")
    for name in (".execution-publication", ".delivery-publication"):
        shutil.rmtree(_intent(child).parent / name)
    with controller.store._connect() as connection:
        connection.execute("UPDATE artifacts SET id = 'legacy-execution' WHERE id = ?", (artifact["id"],))
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND type IN "
            "('materialization_execution_prepared', 'materialization_execution_committed', 'materialization_delivery_prepared')",
            (child.id,),
        )
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND type = 'artifact_recorded' "
            "AND json_extract(payload, '$.path') = ?", (child.id, artifact["path"]),
        )
        controller.store._append_event(
            connection, child.id, artifact["task_id"], "artifact_recorded",
            {"artifact_id": "legacy-execution", "path": artifact["path"], "sha256": artifact["sha256"], "size": artifact["size"]},
        )
    # This reproduces the observable Feature 089 format: terminal receipts and execution
    # evidence exist, but the newer launch protocol did not yet exist.
    _intent(child).unlink()
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, LAUNCH_EVENT))
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    assert _materialize(controller, parent, child, result) == expected

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger


def test_native_process_exit_after_actual_popen_never_reexecutes_candidate(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    script = r'''
import json
import os
import sys
from pathlib import Path

import famou.evolution as evolution
from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import StrategyResult
from famou.runtime import MockRuntime

home, parent_id, child_id, raw_result, raw_contract = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
original = evolution.subprocess.Popen

def actual_process_then_controller_exit(*args, **kwargs):
    process = original(*args, **kwargs)
    # Wait only for the deterministic fixture child to exit, leaving no orphan test process.
    # Returning from Popen to CommandCandidateRunner is deliberately prevented, so it cannot
    # publish either execution.json or its temporary file.
    process.communicate(timeout=5)
    assert process.returncode == 0
    os._exit(83)

evolution.subprocess.Popen = actual_process_then_controller_exit
controller.materialize_evolved_outputs(
    parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)),
    StrategyResult(**json.loads(raw_result)), timeout_seconds=1,
)
raise AssertionError("actual Popen interruption was not reached")
'''
    process = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "home"), parent.id, child.id,
         json.dumps(result.to_dict()), json.dumps(_contract().to_dict())],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert process.returncode == 83, process.stderr
    attempt = _attempt(child, result)
    counter = attempt / "execution-count.txt"
    assert counter.read_text() == "1"
    assert not (attempt / "execution.json").exists()
    assert not (attempt / ".execution.json.tmp").exists()
    assert _intent(child).is_file()
    assert len(_events(controller, child)) == 1
    _assert_no_terminal_claim(controller, parent, child)
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    for _ in range(2):
        with pytest.raises(MaterializationLaunchUncertain):
            _materialize(controller, parent, child, result)
        assert counter.read_text() == "1"
        assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
        assert _database_snapshot(controller, parent, child) == ledger


@pytest.mark.parametrize("node", ["regular", "directory", "symlink", "broken_symlink", "fifo"])
def test_temporary_intent_alone_prevents_cleaning_preexecution_staging(
    tmp_path: Path, monkeypatch, node: str
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    with launch.materialization_lock(child):
        pass
    attempt = _attempt(child, result)
    attempt.mkdir(parents=True)
    (attempt / "staging-only.txt").write_text("retain incomplete launch preparation")
    temporary = _intent(child).with_name(".launch-intent.json.tmp")
    if node == "regular":
        temporary.write_bytes(b"partial intent")
    elif node == "directory":
        temporary.mkdir()
    elif node == "symlink":
        outside = tmp_path / "outside-temporary"
        outside.write_bytes(b"unrelated data")
        temporary.symlink_to(outside)
    elif node == "broken_symlink":
        temporary.symlink_to(tmp_path / "absent-temporary")
    else:
        os.mkfifo(temporary)
    assert not _intent(child).exists()
    assert _events(controller, child) == []
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)
    _deny_runner(monkeypatch)

    with pytest.raises(MaterializationLaunchUncertain):
        _materialize(controller, parent, child, result)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger
    _assert_no_terminal_claim(controller, parent, child)


def test_exact_existing_intent_cannot_authorize_even_the_same_prepare_request(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt_after_intent(monkeypatch, controller, parent, child, result)
    intent = json.loads(_intent(child).read_bytes())
    identity = {key: value for key, value in intent.items() if key not in {"runner_sha256", "timeout_seconds"}}
    runner = CommandCandidateRunner(
        (sys.executable, "-I"), timeout_seconds=1,
        environment={"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"},
    )
    files = _filesystem_snapshot(Path(parent.workspace), Path(child.workspace))
    ledger = _database_snapshot(controller, parent, child)

    with launch.materialization_lock(child), pytest.raises(MaterializationLaunchUncertain):
        launch.prepare_launch_intent(controller.store, child, identity, runner)

    assert _filesystem_snapshot(Path(parent.workspace), Path(child.workspace)) == files
    assert _database_snapshot(controller, parent, child) == ledger
    _assert_no_terminal_claim(controller, parent, child)
