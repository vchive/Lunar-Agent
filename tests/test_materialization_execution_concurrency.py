"""Concurrent execution reconciliation shares the nonblocking materialization lock."""

import json
import subprocess
import sys
from pathlib import Path

from test_materialization_execution import (
    _assert_registered_once,
    _fixture,
    _interrupt,
    _recover_registration_only,
)
from test_materialization_launch import _attempt, _contract
from test_materialization_launch_concurrency import _wait_for_authorization

_RECOVER = r'''
import json
import sys
import time
from pathlib import Path
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import CommandCandidateRunner, EvolutionError, StrategyResult
from lunar_evolution.runtime import MockRuntime

home, parent_id, child_id, raw_contract, raw_result, barrier_directory, mode = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
barriers = Path(barrier_directory)
def forbidden(*args, **kwargs):
    raise AssertionError("execution reconciliation repeated candidate work or output publication")
CommandCandidateRunner.run = forbidden
controller._promote_evolved_outputs = forbidden
def stop_after_registration(*args, **kwargs):
    raise EvolutionError("test stops after execution registration")
controller._resume_materialization_delivery = stop_after_registration
if mode == "first":
    original = controller.store.commit_materialization_execution
    def hold_before_commit(*args, **kwargs):
        (barriers / "first-authorized").write_text("holding lifecycle lock during execution commit")
        deadline = time.monotonic() + 15
        while not (barriers / "release-first").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("execution commit release barrier was not reached")
            time.sleep(0.01)
        return original(*args, **kwargs)
    controller.store.commit_materialization_execution = hold_before_commit
try:
    controller.materialize_evolved_outputs(
        parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)),
        StrategyResult(**json.loads(raw_result)), timeout_seconds=1,
    )
except EvolutionError as exc:
    if mode == "second":
        assert str(exc) == "materialization_already_running", str(exc)
        print(json.dumps({"busy": str(exc)}), flush=True)
    else:
        assert str(exc) != "materialization_already_running", str(exc)
        rows = [row for row in controller.store.list_artifacts(child_id)
                if row["kind"] == "evolved_candidate_execution"]
        assert len(rows) == 1
        print(json.dumps({"registered": True}), flush=True)
else:
    raise AssertionError("execution reconciliation invented an unprepared terminal result")
'''


def test_second_recovery_fails_busy_while_first_registers_the_only_execution(
    tmp_path: Path, monkeypatch,
) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "prepared")
    barriers = tmp_path / "barriers"
    barriers.mkdir()
    command = [
        sys.executable, "-c", _RECOVER, str(tmp_path / "home"), parent.id, child.id,
        json.dumps(_contract().to_dict()), json.dumps(result.to_dict()), str(barriers),
    ]
    processes: list[subprocess.Popen[str]] = []
    try:
        first = subprocess.Popen(
            [*command, "first"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(first)
        _wait_for_authorization(barriers / "first-authorized", first)
        attempt = _attempt(child, result)
        sentinel = attempt / "retain-during-concurrent-recovery.txt"
        sentinel.write_text("first recovery still owns this attempt", encoding="utf-8")
        second = subprocess.Popen(
            [*command, "second"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(second)
        # Deliberately release the first only after the second returned: a blocking lock or
        # a second mutation cannot satisfy this barrier ordering.
        stdout, stderr = second.communicate(timeout=5)
        assert second.returncode == 0, stderr
        assert json.loads(stdout) == {"busy": "materialization_already_running"}
        assert first.poll() is None
        assert sentinel.read_text() == "first recovery still owns this attempt"
        assert (attempt / "execution-count.txt").read_text() == "1"
        (barriers / "release-first").write_text("complete execution registration", encoding="utf-8")
        stdout, stderr = first.communicate(timeout=15)
        assert first.returncode == 0, stderr
        assert json.loads(stdout) == {"registered": True}
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
    _assert_registered_once(controller, child, result)
    _recover_registration_only(monkeypatch, controller, parent, child, result)
