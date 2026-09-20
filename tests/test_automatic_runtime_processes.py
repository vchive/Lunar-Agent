"""Owned runtime and tool commands have independent groups and bounded cleanup."""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from famou.runtime import MockRuntime, RuntimeExecutionError, SubprocessRuntime
from famou.tools import LocalToolRegistry


@pytest.mark.parametrize("stop", ["guard", "cancel"])
def test_late_cancelled_model_response_cannot_write_or_request_again(tmp_path, stop):
    from test_agent_loop import FixtureModel

    from famou.runtime import ModelTurn, ToolCall

    model = FixtureModel([
        ModelTurn("", (ToolCall("1", "write_file", {"path": "late.txt", "content": "late"}),)),
        ModelTurn("unexpected continuation"),
    ])
    runtime = AgentLoopRuntime(model)
    original = model.complete
    stopped = [False]

    def guard():
        if stopped[0]:
            raise SolveExecutionCancelled("candidate_generation")

    runtime.set_continuation_guard(guard)

    def complete(*args, **kwargs):
        turn = original(*args, **kwargs)
        if stop == "guard":
            stopped[0] = True
        else:
            runtime.cancel()
        return turn

    model.complete = complete
    with pytest.raises(SolveExecutionCancelled):
        runtime.run("fixture", tmp_path)
    assert len(model.requests) == 1
    assert not (tmp_path / "late.txt").exists()
    model.complete = original
    stopped[0] = False
    assert runtime.run("new invocation", tmp_path).text == "unexpected continuation"


@pytest.mark.parametrize("isolated", [True, False])
def test_late_final_response_discarded_after_cancellation(tmp_path, isolated):
    from test_agent_loop import FixtureModel

    from famou.runtime import ModelTurn

    model = FixtureModel([ModelTurn("late final")])
    runtime = AgentLoopRuntime(model)
    original = model.complete

    def complete(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.cancel()
        return result

    model.complete = complete
    with pytest.raises(SolveExecutionCancelled):
        (runtime.run_isolated if isolated else runtime.run)("fixture", tmp_path)
    assert len(model.requests) == 1


@pytest.mark.parametrize("stop", ["guard", "cancel"])
def test_cancel_during_tool_blocks_remaining_tools_and_model_requests(tmp_path, stop):
    from test_agent_loop import FixtureModel

    from famou.runtime import ModelTurn, ToolCall

    model = FixtureModel([ModelTurn("", tuple(
        ToolCall(str(index), "write_file", {"path": f"{index}.txt", "content": "fixture"})
        for index in (1, 2)
    )), ModelTurn("late")])
    runtime = AgentLoopRuntime(model)
    stopped = [False]

    def guard():
        if stopped[0]:
            raise SolveExecutionCancelled("candidate_generation")

    runtime.set_continuation_guard(guard)
    original = runtime.tools.execute

    def execute(*args, **kwargs):
        result = original(*args, **kwargs)
        if stop == "guard":
            stopped[0] = True
        else:
            runtime.cancel()
        return result

    runtime.tools.execute = execute
    with pytest.raises(SolveExecutionCancelled):
        runtime.run("fixture", tmp_path)
    assert (tmp_path / "1.txt").read_text() == "fixture"
    assert not (tmp_path / "2.txt").exists()
    assert len(model.requests) == 1


@pytest.mark.parametrize("isolated", [True, False])
def test_guard_budget_exception_preserved_before_request(tmp_path, isolated):
    from test_agent_loop import FixtureModel

    model = FixtureModel([])
    runtime = AgentLoopRuntime(model)
    error = SolveExecutionBudgetExceeded("preparation", started_at=0, deadline=1, observed_at=2)

    def guard():
        raise error

    runtime.set_continuation_guard(guard)
    with pytest.raises(SolveExecutionBudgetExceeded) as caught:
        (runtime.run_isolated if isolated else runtime.run)("fixture", tmp_path)
    assert caught.value is error
    assert model.requests == []


def _observe(target):
    events = []

    def observer(pid, pgid):
        assert pgid == pid == os.getpgid(pid)
        assert pgid != os.getpgrp()
        events.append(("started", pid, pgid))

    target.set_process_observer(observer)
    target.set_process_released(lambda pid, pgid: events.append(("released", pid, pgid)))
    return events


def _assert_released(events):
    assert len(events) == 2
    assert events[0][0] == "started"
    assert events[1] == ("released", *events[0][1:])
    with pytest.raises(ProcessLookupError):
        os.killpg(events[0][2], 0)


def test_subprocess_runtime_tracks_prompt_and_releases_success(tmp_path):
    runtime = SubprocessRuntime([sys.executable, "-c", "import sys; print(sys.stdin.read())"])
    events = _observe(runtime)
    assert runtime.run("fixture prompt", tmp_path, 3).text == "fixture prompt"
    _assert_released(events)
    assert runtime.process_info() == (None, None)


def test_subprocess_runtime_legacy_group_unchanged(tmp_path):
    runtime = SubprocessRuntime([sys.executable, "-c", "import os; print(os.getpgrp())"])
    assert int(runtime.run("fixture", tmp_path, 3).text) == os.getpgrp()


@pytest.mark.parametrize("stop", ["timeout", "cancel", "nonzero", "empty"])
def test_subprocess_runtime_releases_all_terminal_paths(tmp_path, stop):
    code = "import time; time.sleep(60)" if stop in {"timeout", "cancel"} else (
        "raise SystemExit(2)" if stop == "nonzero" else "pass"
    )
    runtime = SubprocessRuntime([sys.executable, "-c", code])
    events = _observe(runtime)
    registered = threading.Event()
    observer = runtime._process_observer

    def observe(pid, pgid):
        observer(pid, pgid)
        registered.set()

    runtime.set_process_observer(observe)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.run, "fixture", tmp_path, 0.1 if stop == "timeout" else 3)
        assert registered.wait(2)
        if stop == "cancel":
            runtime.cancel()
        with pytest.raises(RuntimeExecutionError):
            future.result(timeout=4)
    _assert_released(events)


@pytest.mark.parametrize("keep_pipes", [True, False])
def test_subprocess_runtime_cleans_descendants_after_leader_exit(tmp_path, keep_pipes):
    redirects = "" if keep_pipes else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    code = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']{redirects}); "
        "print('completed', flush=True)"
    )
    runtime = SubprocessRuntime([sys.executable, "-c", code])
    events = _observe(runtime)
    started = time.monotonic()
    assert runtime.run("fixture", tmp_path, 3).text == "completed"
    assert time.monotonic() - started < 2
    _assert_released(events)


def test_subprocess_runtime_start_failure_does_not_release(tmp_path):
    runtime = SubprocessRuntime([str(tmp_path / "missing")])
    events = _observe(runtime)
    with pytest.raises(RuntimeExecutionError):
        runtime.run("fixture", tmp_path, 3)
    assert events == []


def test_subprocess_runtime_cleanup_failure_retains_registration(tmp_path, monkeypatch):
    runtime = SubprocessRuntime([sys.executable, "-c", "print('done')"])
    events = _observe(runtime)
    monkeypatch.setattr(runtime, "_cleanup_owned_process", lambda *args: False)
    with pytest.raises(RuntimeExecutionError, match="cleanup"):
        runtime.run("fixture", tmp_path, 3)
    assert len(events) == 1


def test_subprocess_runtime_observer_errors_do_not_mask_result(tmp_path):
    runtime = SubprocessRuntime([sys.executable, "-c", "print('done')"])

    def broken(*args):
        raise RuntimeError("fixture callback")

    runtime.set_process_observer(broken)
    runtime.set_process_released(broken)
    assert runtime.run("fixture", tmp_path, 3).text == "done"


@pytest.mark.parametrize("stop", ["success", "timeout", "cancel", "nonzero"])
def test_tool_command_registers_and_releases_owned_process(tmp_path, stop):
    registry = LocalToolRegistry(allow_exec=True, command_timeout=0.1 if stop == "timeout" else 3)
    events = _observe(registry)
    if stop == "cancel":
        observer = registry._process_observer

        def cancel(pid, pgid):
            observer(pid, pgid)
            os.killpg(pgid, signal.SIGTERM)

        registry.set_process_observer(cancel)
    code = {"success": "print('done')", "timeout": "import time; time.sleep(60)",
            "cancel": "import time; time.sleep(60)", "nonzero": "raise SystemExit(2)"}[stop]
    result = registry.execute("run_command", {"command": [sys.executable, "-c", code]}, tmp_path)
    assert result.success is (stop == "success")
    _assert_released(events)


def test_tool_command_default_uses_legacy_path(tmp_path, monkeypatch):
    monkeypatch.setattr("famou.candidate_execution_runner._bounded_process_bytes",
                        lambda *a, **k: pytest.fail("tracked path without observer"))
    registry = LocalToolRegistry(allow_exec=True)
    result = registry.execute("run_command", {"command": [sys.executable, "-c", "print('done')"]}, tmp_path)
    assert result.success and result.output == "exit_code=0\nstdout:\ndone\n"


def test_tracked_tool_preserves_explicit_environment_and_shared_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNAR_PROCESS_FIXTURE", "ambient")
    registry = LocalToolRegistry(
        allow_exec=True, command_timeout=3, command_environment={"LUNAR_PROCESS_FIXTURE": "explicit"},
    )
    events = _observe(registry)
    result = registry.execute("run_command", {
        "command": [sys.executable, "-c", "import os; print(os.environ['LUNAR_PROCESS_FIXTURE'])"],
    }, tmp_path)
    assert result.success and "explicit" in result.output and "ambient" not in result.output
    _assert_released(events)
    events.clear()
    with registry.execution_deadline(time.monotonic() + 0.1):
        result = registry.execute("run_command", {
            "command": [sys.executable, "-c", "import time; time.sleep(60)"],
        }, tmp_path)
    assert not result.success and "timed out" in result.output
    assert registry.command_timeout == 3
    _assert_released(events)


@pytest.mark.parametrize("has_model_release", [True, False])
def test_agent_loop_forwards_process_hooks_to_model_and_tools(has_model_release):
    model = MockRuntime()
    model_observers, model_releases = [], []
    model.set_process_observer = model_observers.append
    if has_model_release:
        model.set_process_released = model_releases.append
    tools = LocalToolRegistry(allow_exec=True)
    runtime = AgentLoopRuntime(model, tools=tools)
    observer = lambda pid, pgid: None
    released = lambda pid, pgid: None
    runtime.set_process_observer(observer)
    runtime.set_process_released(released)
    assert model_observers == [observer]
    assert model_releases == ([released] if has_model_release else [])
    assert tools._process_observer is observer
    assert tools._process_released is released
    runtime.set_process_observer(None)
    runtime.set_process_released(None)
    assert tools._process_observer is tools._process_released is None
