"""Preparation callbacks observe owned processes without changing frozen evaluator authority."""
from __future__ import annotations

import json
import os
import signal

import pytest
from test_frozen_evaluator_bundle import EVALUATOR_SOURCE
from test_snapshot_evaluator_bundle import SNAPSHOT_SOURCE, _compile, _runtime

from lunar_evolution import candidate_execution_runner as runner
from lunar_evolution import evaluator_bundle as bundle
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
)


@pytest.mark.parametrize("invocation,source", [("candidate", EVALUATOR_SOURCE), ("snapshot", SNAPSHOT_SOURCE)])
def test_probe_process_callbacks_preserve_frozen_bytes(tmp_path, invocation, source):
    reference = _compile(_runtime(source), tmp_path / "reference", invocation=invocation)
    observed, released = [], []

    def register(pid, pgid):
        assert pid == pgid == os.getpgid(pid)
        assert pgid != os.getpgrp()
        observed.append((pid, pgid))

    tracked = _compile(
        _runtime(source), tmp_path / "tracked", invocation=invocation,
        process_observer=register, process_released=lambda pid, pgid: released.append((pid, pgid)),
    )

    assert len(observed) == 6
    assert observed == released
    for pid, _ in released:
        with pytest.raises(ProcessLookupError):
            os.getpgid(pid)
    assert tracked.fingerprint == reference.fingerprint
    assert {item.name: item.read_bytes() for item in tracked.root.iterdir()} == {
        item.name: item.read_bytes() for item in reference.root.iterdir()
    }


@pytest.mark.parametrize("failure", ["timeout", "cancel", "malformed", "exit"])
def test_candidate_probe_releases_process_on_failure(tmp_path, failure):
    candidate = tmp_path / "candidate.py"
    evaluator = tmp_path / "evaluator.py"
    candidate.write_text("# synthetic candidate\n")
    evaluator.write_text({
        "timeout": "import time\ntime.sleep(60)\n",
        "cancel": "import time\ntime.sleep(60)\n",
        "malformed": "print('invalid report')\n",
        "exit": "raise SystemExit(1)\n",
    }[failure])
    observed, released = [], []

    def register(pid, pgid):
        observed.append((pid, pgid))
        if failure == "cancel":
            os.killpg(pgid, signal.SIGTERM)

    with pytest.raises(bundle.EvaluatorBundleError):
        bundle._run_evaluator(
            evaluator, candidate, 0.1 if failure == "timeout" else 3,
            process_observer=register,
            process_released=lambda pid, pgid: released.append((pid, pgid)),
        )
    assert len(observed) == 1
    assert observed == released
    with pytest.raises(ProcessLookupError):
        os.getpgid(observed[0][0])


def test_candidate_probe_start_failure_does_not_register_or_release(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# synthetic candidate\n")

    def fail_start(*args, **kwargs):
        raise OSError("fixture")

    monkeypatch.setattr(runner.subprocess, "Popen", fail_start)
    with pytest.raises(bundle.EvaluatorBundleError):
        bundle._run_evaluator(
            tmp_path / "evaluator.py", candidate, 3,
            process_observer=lambda *args: pytest.fail("registered a process that did not start"),
            process_released=lambda *args: pytest.fail("released a process that did not start"),
        )


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
@pytest.mark.parametrize("stop", ["budget", "cancel"])
def test_preflight_preserves_typed_operational_stop(tmp_path, monkeypatch, invocation, stop):
    error = (SolveExecutionBudgetExceeded("preparation", started_at=0, deadline=1, observed_at=2)
             if stop == "budget" else SolveExecutionCancelled("preparation"))

    def stopped(*args, **kwargs):
        raise error

    monkeypatch.setattr(runner, "_bounded_process_bytes", stopped)
    source = EVALUATOR_SOURCE if invocation == "candidate" else SNAPSHOT_SOURCE
    with pytest.raises(type(error)) as raised:
        _compile(_runtime(source), tmp_path, invocation=invocation,
                 process_observer=lambda pid, pgid: None)
    assert raised.value is error
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize("callback", ["process_observer", "process_released"])
def test_invalid_callback_rejected_before_compiler_request(tmp_path, callback):
    runtime = _runtime()
    with pytest.raises(TypeError, match=callback):
        _compile(runtime, tmp_path, **{callback: 1})
    assert runtime.bundle_calls == runtime.audit_calls == 0


def test_unobserved_candidate_probe_keeps_legacy_runner(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# synthetic candidate\n")
    monkeypatch.setattr(runner, "_bounded_process_bytes", lambda *a, **k: pytest.fail("new runner"))
    report = {"schema_version": "1", "evaluator_id": "fixture", "validity": 1,
              "quality": 1, "combined_score": 1, "detailed_scores": {}, "error_info": []}
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(f"print({json.dumps(json.dumps(report))})\n")
    assert bundle._run_evaluator(evaluator, candidate, 3).validity == 1
