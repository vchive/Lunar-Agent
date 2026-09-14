"""One lifecycle owner advances a prepared delivery while peers fail promptly."""

import json
import subprocess
import sys
from pathlib import Path

from test_materialization_delivery import (
    _fixture,
    _interrupt,
    _replay_complete,
)
from test_materialization_launch import _attempt, _contract
from test_materialization_launch_concurrency import _wait_for_authorization

_DELIVER = r'''
import json
import sys
import time
from pathlib import Path
from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import CommandCandidateRunner, EvolutionError, StrategyResult
from famou.runtime import MockRuntime
home, parent_id, child_id, raw_contract, raw_result, barriers_path, mode = sys.argv[1:]
controller = LocalController(Config(Path(home)), MockRuntime())
barriers = Path(barriers_path)
def forbidden_runner(*args, **kwargs):
    raise AssertionError("delivery recovery entered the candidate runner again")
CommandCandidateRunner.run = forbidden_runner
if mode == "first":
    original = controller.store.commit_output_publication
    def hold_before_commit(*args, **kwargs):
        (barriers / "first-authorized").write_text("delivery owns lifecycle and output locks")
        deadline = time.monotonic() + 15
        while not (barriers / "release-first").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("delivery release barrier was not reached")
            time.sleep(0.01)
        return original(*args, **kwargs)
    controller.store.commit_output_publication = hold_before_commit
try:
    payload = controller.materialize_evolved_outputs(
        parent_id, child_id, AlgorithmProblemContract.from_dict(json.loads(raw_contract)),
        StrategyResult(**json.loads(raw_result)), timeout_seconds=1,
    )
except EvolutionError as exc:
    assert mode == "second" and str(exc) == "materialization_already_running", str(exc)
    print(json.dumps({"busy": str(exc)}), flush=True)
else:
    assert mode == "first", "concurrent caller must return busy before first commits"
    print(json.dumps(payload), flush=True)
'''


def test_second_delivery_recovery_fails_busy_then_reuses_first_completed_result(tmp_path: Path, monkeypatch) -> None:
    controller, parent, child, result = _fixture(tmp_path)
    _interrupt(monkeypatch, controller, parent, child, result, "plan")
    barriers = tmp_path / "barriers"
    barriers.mkdir()
    command = [
        sys.executable, "-c", _DELIVER, str(tmp_path / "home"), parent.id, child.id,
        json.dumps(_contract().to_dict()), json.dumps(result.to_dict()), str(barriers),
    ]
    processes: list[subprocess.Popen[str]] = []
    try:
        first = subprocess.Popen([*command, "first"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(first)
        _wait_for_authorization(barriers / "first-authorized", first)
        attempt = _attempt(child, result)
        sentinel = attempt / "retain-concurrent-delivery.txt"
        sentinel.write_text("first delivery owns this attempt", encoding="utf-8")
        second = subprocess.Popen([*command, "second"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(second)
        # Keep the first transaction blocked until the competing lifecycle call returned.
        stdout, stderr = second.communicate(timeout=5)
        assert second.returncode == 0, stderr
        assert json.loads(stdout) == {"busy": "materialization_already_running"}
        assert first.poll() is None
        assert sentinel.read_text() == "first delivery owns this attempt"
        assert (attempt / "execution-count.txt").read_text() == "1"
        (barriers / "release-first").write_text("commit and finish terminal publication", encoding="utf-8")
        stdout, stderr = first.communicate(timeout=15)
        assert first.returncode == 0, stderr
        expected = json.loads(stdout)
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
    assert _replay_complete(monkeypatch, controller, parent, child, result) == expected
