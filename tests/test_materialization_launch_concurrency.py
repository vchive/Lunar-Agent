"""The complete final-candidate lifecycle has one nonblocking child owner."""

import json
import subprocess
import sys
import time
from pathlib import Path

from test_materialization_launch import (
    _attempt,
    _contract,
    _deny_runner,
    _events,
    _fixture,
    _materialize,
)

_MATERIALIZE = r'''
import json
import sys
import time
from pathlib import Path

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import CommandCandidateRunner, EvolutionError, StrategyResult
from lunar_evolution.runtime import MockRuntime

home, parent_id, child_id, raw_result, raw_contract, barrier_directory, mode = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
barriers = Path(barrier_directory)
if mode == "first":
    original = CommandCandidateRunner.run
    def hold_before_first_runner(self, *args, **kwargs):
        (barriers / "first-authorized").write_text("runner entry reached while owning lifecycle lock")
        deadline = time.monotonic() + 15
        while not (barriers / "release-first").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("first materialization release barrier was not reached")
            time.sleep(0.01)
        return original(self, *args, **kwargs)
    CommandCandidateRunner.run = hold_before_first_runner
else:
    def forbidden_runner(*args, **kwargs):
        raise AssertionError("concurrent materialization entered the runner")
    CommandCandidateRunner.run = forbidden_runner

try:
    payload = controller.materialize_evolved_outputs(
        parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)),
        StrategyResult(**json.loads(raw_result)), timeout_seconds=1,
    )
except EvolutionError as exc:
    if mode != "second" or str(exc) != "materialization_already_running":
        raise
    print(json.dumps({"busy": str(exc)}), flush=True)
else:
    assert mode == "first", "concurrent call must fail busy before terminal result exists"
    print(json.dumps(payload, sort_keys=True), flush=True)
'''


def _wait_for_authorization(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while not path.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(f"first materialization exited before authorization\n{stdout}\n{stderr}")
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for first materialization authorization")
        time.sleep(0.01)


def test_second_fresh_materialization_fails_busy_then_reuses_one_completed_execution(
    tmp_path: Path, monkeypatch
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    barriers = tmp_path / "barriers"
    barriers.mkdir()
    command = [
        sys.executable, "-c", _MATERIALIZE, str(tmp_path / "home"), parent.id, child.id,
        json.dumps(result.to_dict()), json.dumps(_contract().to_dict()), str(barriers),
    ]
    processes: list[subprocess.Popen[str]] = []
    try:
        first = subprocess.Popen(
            [*command, "first"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(first)
        _wait_for_authorization(barriers / "first-authorized", first)
        attempt = _attempt(child, result)
        assert attempt.is_dir()
        sentinel = attempt / "first-owner-sentinel.txt"
        sentinel.write_text("second caller must not clean this attempt", encoding="utf-8")
        second = subprocess.Popen(
            [*command, "second"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(second)
        # The first process is deliberately not released until the second has returned. A
        # blocking flock, a missing lifecycle lock, or a second cleanup cannot pass this test.
        second_stdout, second_stderr = second.communicate(timeout=5)
        assert second.returncode == 0, second_stderr
        assert json.loads(second_stdout) == {"busy": "materialization_already_running"}
        assert first.poll() is None
        assert sentinel.read_text() == "second caller must not clean this attempt"
        assert not (attempt / "execution-count.txt").exists()
        assert len(_events(controller, child)) == 1
        (barriers / "release-first").write_text("complete the single authorized run", encoding="utf-8")
        first_stdout, first_stderr = first.communicate(timeout=15)
        assert first.returncode == 0, first_stderr
        expected = json.loads(first_stdout)
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

    assert expected["status"] == "succeeded"
    assert (attempt / "execution-count.txt").read_text() == "1"
    _deny_runner(monkeypatch)
    assert _materialize(controller, parent, child, result) == expected
    assert (attempt / "execution-count.txt").read_text() == "1"
    assert len(_events(controller, child)) == 1
    assert len([
        event for event in controller.store.list_events(child.id)
        if event["type"] == "evolved_candidate_executed"
    ]) == 1
    assert len([
        event for event in controller.store.list_events(parent.id)
        if event["type"] == "evolved_candidate_materialized"
    ]) == 1
