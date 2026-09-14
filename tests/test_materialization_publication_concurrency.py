"""A child lock serializes real processes recovering the same prepared terminal result."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_materialization_publication import (
    COMMITTED_EVENT,
    PREPARED_EVENT,
    RESULT_RELATIVE,
    TERMINAL_EVENT,
    SimulatedCrash,
    _assert_execution_count,
    _contract,
    _directory,
    _fixture,
    _marker,
    _materialize,
)

_RECOVER = r'''
import fcntl
import hashlib
import json
import sys
import time
from pathlib import Path

from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import CommandCandidateRunner, StrategyResult
from famou.materialization_publication import recover_materialization_result
from famou.output_publication import recover_outputs
from famou.runtime import MockRuntime

home, parent_id, child_id, raw_result, raw_contract, barrier_directory, mode = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
parent = controller.store.get_run(parent_id)
child = controller.store.get_run(child_id)
assert parent is not None and child is not None
result = StrategyResult(**json.loads(raw_result))
contract = AlgorithmProblemContract.from_dict(json.loads(raw_contract))
barriers = Path(barrier_directory)

def unexpected(*args, **kwargs):
    raise AssertionError("terminal recovery invoked a candidate or output publisher")

CommandCandidateRunner.run = unexpected
controller._promote_evolved_outputs = unexpected
recover_outputs(controller.store, parent, child.id, contract.outputs)
paused = False

def validate(payload):
    global paused
    controller._validate_materialization_links(parent, child, contract, result.strategy)
    source = controller._validate_materialization_result_identity(child, contract, result)
    digest = hashlib.sha256(source).hexdigest()
    attempt = "evolution/materialization/" + result.best_candidate_id + "-" + digest[:12]
    controller._validate_materialization_replay(
        payload, parent, child, contract, result, digest, attempt,
    )
    if mode == "first" and not paused:
        paused = True
        (barriers / "first-validated").write_text("holding child lock", encoding="utf-8")
        deadline = time.monotonic() + 15
        while not (barriers / "release-first").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("terminal recovery release barrier was not reached")
            time.sleep(0.01)

if mode == "second":
    original_flock = fcntl.flock
    def observe_contended_lock(descriptor, operation):
        if operation != fcntl.LOCK_EX:
            return original_flock(descriptor, operation)
        try:
            original_flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            (barriers / "second-contended").write_text("waiting for child lock", encoding="utf-8")
        else:
            raise AssertionError("second recovery bypassed the first process child lock")
        original_flock(descriptor, operation)
        (barriers / "second-acquired").write_text("child lock acquired", encoding="utf-8")
    fcntl.flock = observe_contended_lock

payload = recover_materialization_result(controller.store, parent, child, validate=validate)
assert payload is not None
print(json.dumps(payload, sort_keys=True), flush=True)
'''


def _wait_for_barrier(path: Path, processes: list[subprocess.Popen[str]]) -> None:
    deadline = time.monotonic() + 15
    while not path.exists():
        for process in processes:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    f"recovery exited before {path.name}: {process.returncode}\n{stdout}\n{stderr}"
                )
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def test_child_lock_serializes_real_recovery_of_one_prepared_terminal_result(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    original_prepare = controller.store.prepare_materialization_publication

    def prepared_then_interrupted(*args, **kwargs):
        original_prepare(*args, **kwargs)
        raise SimulatedCrash("leave a durable prepared result for recovery")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "prepare_materialization_publication", prepared_then_interrupted)
        with pytest.raises(SimulatedCrash):
            _materialize(controller, parent, child, result)
    expected = json.loads((_directory(child) / "result.blob").read_bytes())
    assert not _marker(child).exists()
    barriers = tmp_path / "barriers"
    barriers.mkdir()
    command = [
        sys.executable, "-c", _RECOVER, str(tmp_path / "home"), parent.id, child.id,
        json.dumps(result.to_dict()), json.dumps(_contract().to_dict()), str(barriers),
    ]
    processes: list[subprocess.Popen[str]] = []
    try:
        first = subprocess.Popen(
            [*command, "first"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(first)
        _wait_for_barrier(barriers / "first-validated", processes)
        second = subprocess.Popen(
            [*command, "second"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(second)
        _wait_for_barrier(barriers / "second-contended", processes)

        assert not (barriers / "second-acquired").exists()
        assert not _marker(child).exists()
        assert not any(
            row["kind"] == "evolved_materialization"
            for row in controller.store.list_artifacts(child.id)
        )
        (barriers / "release-first").write_text("complete terminal result", encoding="utf-8")
        first_stdout, first_stderr = first.communicate(timeout=15)
        second_stdout, second_stderr = second.communicate(timeout=15)
        assert first.returncode == 0, first_stderr
        assert second.returncode == 0, second_stderr
        assert json.loads(first_stdout) == json.loads(second_stdout) == expected
        assert (barriers / "second-acquired").is_file()
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)

    assert json.loads(_marker(child).read_bytes()) == expected
    assert (_directory(child) / "completed.json").is_file()
    assert len([
        row for row in controller.store.list_artifacts(child.id)
        if row["kind"] == "evolved_materialization"
    ]) == 1
    child_events = controller.store.list_events(child.id)
    assert len([event for event in child_events if event["type"] == PREPARED_EVENT]) == 1
    assert len([event for event in child_events if event["type"] == COMMITTED_EVENT]) == 1
    assert len([
        event for event in child_events
        if event["type"] == "artifact_recorded" and event["payload"].get("path") == RESULT_RELATIVE
    ]) == 1
    assert len([
        event for event in controller.store.list_events(parent.id)
        if event["type"] == TERMINAL_EVENT
    ]) == 1
    _assert_execution_count(child, "success")
