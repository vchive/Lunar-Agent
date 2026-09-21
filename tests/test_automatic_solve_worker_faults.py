"""Independent launch failure probes never start a model or candidate runtime."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import automatic_solve_worker as worker
from lunar_evolution.automatic_solve_lifecycle import own_automatic_solve
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.runtime import MockRuntime


@pytest.fixture
def launch_context(tmp_path):
    config = Config(tmp_path / "home")
    controller = LocalController(config, MockRuntime())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run = controller.store.create_run("offline launcher failure", workspace)
    args = SimpleNamespace(runtime="mock", api_key=None)
    return config, args, controller, run


class FakeChild:
    pid = 424242

    def __init__(self, *, exits_before_signal=False, denied_signal=False):
        self.returncode = None
        self.exits_before_signal = exits_before_signal
        self.denied_signal = denied_signal
        self.signals = []
        self.waited = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.signals.append("terminate")
        if self.denied_signal:
            raise PermissionError("fixture cannot confirm cleanup")
        self.returncode = 0 if self.exits_before_signal else -15
        if self.exits_before_signal:
            raise ProcessLookupError("child exited immediately before terminate")

    def kill(self):
        self.signals.append("kill")
        self.returncode = -9

    def wait(self, timeout):
        assert timeout <= 2
        self.waited = True
        return self.returncode


def _launch(context):
    config, args, controller, run = context
    with own_automatic_solve(run.id, run.workspace) as owner:
        worker.launch_automatic_solve(config, args, controller, run, owner)


@pytest.mark.parametrize("committed", [False, True])
def test_database_claim_exception_reaps_child_and_clears_only_its_registration(
    launch_context, monkeypatch, committed,
):
    _, _, controller, run = launch_context
    child = FakeChild()
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: child)
    original_claim = controller.store.claim_runner_process

    def failed_claim(run_id, pid, pgid):
        if committed:
            assert original_claim(run_id, pid, pgid)
        raise sqlite3.OperationalError("fixture database unavailable")

    monkeypatch.setattr(controller.store, "claim_runner_process", failed_claim)
    with pytest.raises(ValueError, match="explicit resume") as raised:
        _launch(launch_context)
    assert isinstance(raised.value.__cause__, sqlite3.OperationalError)
    assert child.waited and child.returncode is not None
    current = controller.store.get_run(run.id)
    assert (current.runner_pid, current.runner_pgid) == (None, None)
    assert current.status.value == "pending"


def test_failed_claim_reaps_new_child_without_clearing_other_runner(launch_context, monkeypatch):
    _, _, controller, run = launch_context
    controller.store.set_runner_process(run.id, 111111, 111111)
    child = FakeChild()
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(ValueError, match="explicit resume"):
        _launch(launch_context)
    assert child.waited and child.signals == ["terminate"]
    current = controller.store.get_run(run.id)
    assert (current.runner_pid, current.runner_pgid) == (111111, 111111)


def test_child_exiting_between_poll_and_terminate_preserves_launch_error(
    launch_context, monkeypatch,
):
    _, _, controller, run = launch_context
    child = FakeChild(exits_before_signal=True)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: child)
    # No fake child owns the pipe read end: opening its gate raises BrokenPipeError.
    with pytest.raises(ValueError, match="explicit resume") as raised:
        _launch(launch_context)
    assert isinstance(raised.value.__cause__, BrokenPipeError)
    assert child.waited and child.returncode == 0 and child.signals == ["terminate"]
    current = controller.store.get_run(run.id)
    assert (current.runner_pid, current.runner_pgid) == (None, None)


def test_unconfirmed_child_cleanup_retains_its_registration(launch_context, monkeypatch):
    _, _, controller, run = launch_context
    child = FakeChild(denied_signal=True)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(ValueError, match="explicit resume") as raised:
        _launch(launch_context)
    assert isinstance(raised.value.__cause__, BrokenPipeError)
    assert child.returncode is None
    current = controller.store.get_run(run.id)
    assert (current.runner_pid, current.runner_pgid) == (child.pid, child.pid)


@pytest.mark.parametrize("when", ["before_registration", "after_gate"])
def test_real_fast_child_exit_cannot_leave_a_late_runner_registration(
    launch_context, monkeypatch, when,
):
    config, _, controller, run = launch_context
    popen, write = subprocess.Popen, os.write
    children = []

    def fast_child(command, **kwargs):
        if when == "before_registration":
            command = [sys.executable, "-c", "pass"]
        else:
            gate = command[command.index("--gate-fd") + 1]
            command = [
                sys.executable, "-c",
                ("import os,sys; from lunar_evolution.store import Store; "
                 "assert os.read(int(sys.argv[1]), 1) == b'1'; "
                 "assert Store(sys.argv[2]).clear_runner_process(sys.argv[3], os.getpid(), os.getpgrp())"),
                gate, str(config.database), run.id,
            ]
        process = popen(command, **kwargs)
        children.append(process)
        if when == "before_registration":
            assert process.wait(timeout=5) == 0
        return process

    def wait_after_gate(fd, data):
        result = write(fd, data)
        assert children[0].wait(timeout=5) == 0
        return result

    monkeypatch.setattr(worker.subprocess, "Popen", fast_child)
    if when == "after_gate":
        monkeypatch.setattr(worker.os, "write", wait_after_gate)
    try:
        if when == "before_registration":
            with pytest.raises(ValueError, match="explicit resume"):
                _launch(launch_context)
        else:
            _launch(launch_context)
        current = controller.store.get_run(run.id)
        assert (current.runner_pid, current.runner_pgid) == (None, None)
        assert children[0].poll() == 0
        assert current.status.value == "pending"
        assert not (Path(run.workspace) / "solve").exists()
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
