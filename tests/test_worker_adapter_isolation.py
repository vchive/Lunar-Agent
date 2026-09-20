"""Attempt adapter allocation must keep cancellation and observers independently owned."""

import gc
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from famou.agents import (
    AgentInvocationError,
    AgentRegistry,
    AgentRequest,
    AgentResult,
    AgentSelectionError,
    CommandAgentAdapter,
    RuntimeAgentAdapter,
)
from famou.runtime import MockRuntime, RuntimeResult


def request(workspace: Path, task_id: str = "task") -> AgentRequest:
    return AgentRequest("run", task_id, "worker", "work", workspace=workspace, timeout=5)


class IndependentAdapter:
    name = "fixture"
    roles = frozenset({"worker"})
    capabilities = frozenset({"read_files"})

    def __init__(self):
        self.cancelled = threading.Event()
        self.observer = None

    def run(self, request):
        return AgentResult(self.name, request.role, "complete")

    def cancel(self):
        self.cancelled.set()

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        self.observer = observer


class IndependentRuntime:
    name = "independent"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.observer = None
        self.released = None
        self.guard = None
        self.sink = None
        self.context = None
        self.session = None

    def __deepcopy__(self, memo):
        raise AssertionError("runtime state must never be copied")

    def set_context(self, run_id, task_id, prompt):
        self.context = (run_id, task_id, prompt)

    def set_session_path(self, path):
        self.session = path

    def set_event_sink(self, sink):
        self.sink = sink

    def set_process_observer(self, observer):
        self.observer = observer

    def set_process_released(self, released):
        self.released = released

    def set_continuation_guard(self, guard):
        self.guard = guard

    def process_info(self):
        return (None, None)

    def run(self, prompt, workspace, timeout=None):
        if self.guard:
            self.guard()
        if self.observer:
            self.observer(123, 123)
        self.started.set()
        assert self.release.wait(5)
        if self.sink:
            self.sink("runtime_event", {"message": "complete"})
        if self.released:
            self.released(123, 123)
        return RuntimeResult("cancelled" if self.cancelled.is_set() else "complete")

    def cancel(self):
        self.cancelled.set()
        self.release.set()


def test_command_attempts_cancel_and_observe_independently(tmp_path):
    command = (
        "import json,pathlib,sys,time; r=json.load(sys.stdin); "
        "release=pathlib.Path(r['workspace'])/'release'; "
        "\nwhile not release.exists(): time.sleep(0.01)"
        "\nprint(json.dumps({'text':r['task_id']}))"
    )
    prototype = CommandAgentAdapter(
        [sys.executable, "-c", command], name="fixture", capabilities=("read_files",),
    )
    prototype.set_process_observer(lambda *_: pytest.fail("prototype observer must not run"))
    registry = AgentRegistry([prototype])
    first = registry.create_execution_adapter("worker", ("read_files",))
    second = registry.create_execution_adapter("worker", preferred="fixture")
    assert first is not second and first is not prototype
    started = [threading.Event(), threading.Event()]
    observed = [[], []]

    def observe(index, pid, pgid):
        observed[index].append((pid, pgid))
        started[index].set()

    first.set_process_observer(lambda pid, pgid: observe(0, pid, pgid))
    second.set_process_observer(lambda pid, pgid: observe(1, pid, pgid))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(first.run, request(tmp_path / "first", "first"))
        second_result = executor.submit(second.run, request(tmp_path / "second", "second"))
        try:
            assert all(event.wait(3) for event in started)
            assert len(observed[0]) == len(observed[1]) == 1
            assert observed[0][0][0] != observed[1][0][0]
            assert all(values[0][0] == values[0][1] for values in observed)
            first.cancel()
            with pytest.raises(AgentInvocationError, match="exited with code"):
                first_result.result(timeout=3)
            assert not second_result.done()
            assert second.process_info()[0] == observed[1][0][0]
            (tmp_path / "second" / "release").touch()
            assert second_result.result(timeout=3).text == "second"
            assert prototype.process_info() == (None, None)
        finally:
            first.cancel()
            second.cancel()


def test_runtime_attempts_have_independent_cancellation_observers_and_sessions(tmp_path):
    original = IndependentRuntime()
    prototype = RuntimeAgentAdapter(original, runtime_factory=IndependentRuntime)
    prototype.set_event_sink(lambda *_: pytest.fail("prototype event sink must not run"))
    registry = AgentRegistry([prototype])
    first = registry.create_execution_adapter("worker")
    second = registry.create_execution_adapter("worker")
    assert first.runtime is not second.runtime and first.runtime is not original
    observations, releases, events = [[], []], [[], []], [[], []]
    for index, adapter in enumerate((first, second)):
        adapter.set_process_observer(lambda *args, i=index: observations[i].append(args))
        adapter.set_process_released(lambda *args, i=index: releases[i].append(args))
        adapter.set_event_sink(lambda *args, i=index: events[i].append(args))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(first.run, request(tmp_path / "first", "first"))
        second_result = executor.submit(second.run, request(tmp_path / "second", "second"))
        try:
            assert first.runtime.started.wait(3) and second.runtime.started.wait(3)
            first.cancel()
            assert first_result.result(timeout=3).text == "cancelled"
            assert not second.runtime.cancelled.is_set()
            assert not second_result.done()
            second.runtime.release.set()
            assert second_result.result(timeout=3).text == "complete"
        finally:
            first.cancel()
            second.cancel()
    assert observations == [[(123, 123)], [(123, 123)]]
    assert releases == [[(123, 123)], [(123, 123)]]
    assert all(len(items) == 1 for items in events)
    assert first.runtime.context[1] == "first" and second.runtime.context[1] == "second"
    assert first.runtime.session == tmp_path / "first" / "session-transcript.jsonl"
    assert second.runtime.session == tmp_path / "second" / "session-transcript.jsonl"
    assert original.context is original.observer is original.sink is None


def test_runtime_requires_explicit_factory_but_legacy_selection_still_runs(tmp_path):
    prototype = RuntimeAgentAdapter(MockRuntime())
    registry = AgentRegistry([prototype])
    assert registry.select("worker") is prototype
    assert "Mock runtime" in prototype.run(request(tmp_path)).text
    with pytest.raises(AgentInvocationError, match="runtime_factory"):
        registry.create_execution_adapter("worker")


def test_unknown_adapter_requires_factory_but_legacy_selection_still_runs(tmp_path):
    prototype = IndependentAdapter()
    registry = AgentRegistry([prototype])
    assert registry.select("worker") is prototype
    assert prototype.run(request(tmp_path)).text == "complete"
    with pytest.raises(AgentInvocationError, match="execution_factory"):
        registry.create_execution_adapter("worker")


def test_custom_adapter_factory_is_explicit_and_preserves_selection_contract():
    prototype = IndependentAdapter()
    registry = AgentRegistry()
    registry.register(prototype, execution_factory=IndependentAdapter)
    with ThreadPoolExecutor(max_workers=2) as executor:
        executions = list(executor.map(lambda _: registry.create_execution_adapter("worker"), range(2)))
    executions[0].cancel()
    executions[0].set_process_observer(lambda *_: None)
    assert not executions[1].cancelled.is_set() and executions[1].observer is None
    assert not prototype.cancelled.is_set() and prototype.observer is None
    assert registry.select("worker", ("read_files",), "fixture") is prototype
    with pytest.raises(AgentSelectionError, match="incompatible"):
        registry.create_execution_adapter("worker", ("write_files",), "fixture")


@pytest.mark.parametrize("kind", ["adapter", "runtime"])
def test_factory_cannot_reuse_registered_prototype(kind):
    registry = AgentRegistry()
    if kind == "adapter":
        prototype = IndependentAdapter()
        registry.register(prototype, execution_factory=lambda: prototype)
    else:
        runtime = MockRuntime()
        registry.register(RuntimeAgentAdapter(runtime, runtime_factory=lambda: runtime))
    with pytest.raises(AgentInvocationError, match="registered"):
        registry.create_execution_adapter("worker")


@pytest.mark.parametrize("kind", ["adapter", "runtime"])
def test_factory_cannot_reuse_previous_attempt_object(kind):
    registry = AgentRegistry()
    if kind == "adapter":
        cached = IndependentAdapter()
        registry.register(IndependentAdapter(), execution_factory=lambda: cached)
    else:
        cached = MockRuntime()
        registry.register(RuntimeAgentAdapter(MockRuntime(), runtime_factory=lambda: cached))
    execution = registry.create_execution_adapter("worker")
    with pytest.raises(AgentInvocationError, match="prior"):
        registry.create_execution_adapter("worker")
    assert execution is not None


def test_factory_cannot_wrap_another_registered_runtime():
    shared = MockRuntime()
    registry = AgentRegistry([
        RuntimeAgentAdapter(MockRuntime(), name="first", runtime_factory=lambda: shared),
        RuntimeAgentAdapter(shared, name="second", runtime_factory=MockRuntime),
    ])
    with pytest.raises(AgentInvocationError, match="registered"):
        registry.create_execution_adapter("worker", preferred="first")


@pytest.mark.parametrize("field,value", [
    ("name", "changed"), ("roles", frozenset({"solver"})),
    ("capabilities", frozenset({"write_files"})), ("run", None),
])
def test_factory_cannot_change_declared_adapter_contract(field, value):
    def factory():
        adapter = IndependentAdapter()
        setattr(adapter, field, value)
        return adapter

    registry = AgentRegistry()
    registry.register(IndependentAdapter(), execution_factory=factory)
    with pytest.raises(AgentInvocationError, match="adapter"):
        registry.create_execution_adapter("worker")


def test_runtime_factory_must_return_valid_runtime():
    registry = AgentRegistry([RuntimeAgentAdapter(MockRuntime(), runtime_factory=lambda: None)])
    with pytest.raises(AgentInvocationError, match="invalid runtime"):
        registry.create_execution_adapter("worker")


def test_builtin_subclass_requires_explicit_factory():
    class CustomRuntimeAdapter(RuntimeAgentAdapter):
        pass

    registry = AgentRegistry([CustomRuntimeAdapter(MockRuntime(), runtime_factory=MockRuntime)])
    with pytest.raises(AgentInvocationError, match="execution_factory"):
        registry.create_execution_adapter("worker")


def test_completed_execution_objects_are_not_retained_by_registry():
    registry = AgentRegistry([RuntimeAgentAdapter(MockRuntime(), runtime_factory=MockRuntime)])
    execution = registry.create_execution_adapter("worker")
    adapter_ref, runtime_ref = weakref.ref(execution), weakref.ref(execution.runtime)
    del execution
    gc.collect()
    assert adapter_ref() is None and runtime_ref() is None


def test_runtime_guard_forwards_and_rejects_late_result(tmp_path):
    runtime = IndependentRuntime()
    adapter = RuntimeAgentAdapter(runtime)

    def guard():
        if runtime.cancelled.is_set():
            raise RuntimeError("attempt cancelled")

    adapter.set_continuation_guard(guard)
    assert runtime.guard is guard
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(adapter.run, request(tmp_path))
        assert runtime.started.wait(3)
        adapter.cancel()
        with pytest.raises(AgentInvocationError, match="attempt cancelled"):
            result.result(timeout=3)
    adapter.set_continuation_guard(None)
    adapter.set_process_released(None)
    assert runtime.guard is runtime.released is None


def test_command_guard_blocks_start_without_process(tmp_path):
    adapter = CommandAgentAdapter([sys.executable, "-c", "print('wrong')"])

    def guard():
        raise RuntimeError("attempt cancelled")

    adapter.set_continuation_guard(guard)
    adapter.set_process_observer(lambda *_: pytest.fail("process must not start"))
    with pytest.raises(RuntimeError, match="attempt cancelled"):
        adapter.run(request(tmp_path / "not-created"))
    assert not (tmp_path / "not-created").exists()


def test_command_observer_failure_cleans_spawned_process(tmp_path):
    adapter = CommandAgentAdapter([sys.executable, "-c", "import time; time.sleep(10)"])
    processes = []

    def observer(*_):
        processes.append(adapter._process)
        raise RuntimeError("ownership rejected")

    adapter.set_process_observer(observer)
    with pytest.raises(RuntimeError, match="ownership rejected"):
        adapter.run(request(tmp_path))
    assert len(processes) == 1 and processes[0].poll() is not None
    assert adapter.process_info() == (None, None)


@pytest.mark.parametrize("action", ["timeout", "cancel"])
def test_command_ignoring_term_is_killed_and_reaped_with_bounded_cleanup(tmp_path, action):
    code = (
        "import json,pathlib,signal,sys,time; r=json.load(sys.stdin); "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "pathlib.Path(r['workspace'],'ready').touch(); time.sleep(30)"
    )
    adapter = CommandAgentAdapter([sys.executable, "-c", code])
    processes, releases = [], []
    adapter.set_process_observer(lambda *_: processes.append(adapter._process))
    adapter.set_process_released(lambda *identity: releases.append(identity))
    bounded_request = AgentRequest(
        "run", "task", "worker", "work", workspace=tmp_path,
        timeout=0.4 if action == "timeout" else 5,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(adapter.run, bounded_request)
        try:
            deadline = time.monotonic() + 3
            while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert (tmp_path / "ready").exists()
            if action == "cancel":
                adapter.cancel()
            with pytest.raises(AgentInvocationError, match="timed out|exited with code"):
                result.result(timeout=3)
            assert processes[0].returncode == -signal.SIGKILL
            assert releases == [(processes[0].pid, processes[0].pid)]
            with pytest.raises(ProcessLookupError):
                os.killpg(processes[0].pid, 0)
        finally:
            adapter.cancel()


def test_command_cancel_cleans_descendants_and_leaves_unrelated_process(tmp_path):
    # The leader handles TERM by reaping its child, so Linux does not depend on PID 1
    # promptly reaping an orphan. The descendant redirects its pipes to permit normal
    # stdout completion; final cleanup must still account for its process group.
    child_code = "import time; time.sleep(30)"
    code = (
        "import json,pathlib,signal,subprocess,sys,time; r=json.load(sys.stdin); "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "pathlib.Path(r['workspace'],'child').write_text(str(child.pid)); "
        "signal.signal(signal.SIGTERM,lambda *_:(child.wait(),sys.exit(0))); "
        "print(json.dumps({'text':'complete'}),flush=True); "
        "sys.stdout.close(); sys.stderr.close(); "
        "time.sleep(30)"
    )
    # This fixture exercises cancellation while both leader and child remain available
    # for verified group cleanup, avoiding an already reaped leader as signal authority.
    adapter = CommandAgentAdapter([sys.executable, "-c", code])
    independent = CommandAgentAdapter([sys.executable, "-c", "import time; time.sleep(30)"])
    released = []
    adapter.set_process_released(lambda *args: released.append(args))
    unrelated_started = threading.Event()
    independent.set_process_observer(lambda *_: unrelated_started.set())
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = executor.submit(adapter.run, request(tmp_path))
        unrelated = executor.submit(independent.run, request(tmp_path / "other"))
        try:
            deadline = time.monotonic() + 3
            while not (tmp_path / "child").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert (tmp_path / "child").exists() and unrelated_started.wait(3)
            child_pid = int((tmp_path / "child").read_text())
            adapter.cancel()
            assert result.result(timeout=3).text == "complete"
            assert not unrelated.done() and independent.process_info()[0] is not None
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
            assert len(released) == 1
        finally:
            adapter.cancel()
            independent.cancel()
            with pytest.raises(AgentInvocationError):
                unrelated.result(timeout=3)


def test_command_cleanup_failure_retains_handle_without_release(tmp_path, monkeypatch):
    adapter = CommandAgentAdapter([sys.executable, "-c", "print('complete')"])
    releases = []
    adapter.set_process_released(lambda *args: releases.append(args))
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "_cleanup_owned_process", lambda *_: False)
        with pytest.raises(AgentInvocationError, match="cleanup could not be confirmed"):
            adapter.run(request(tmp_path))
    assert releases == []
    assert adapter._process.returncode == 0
    assert adapter.process_info() == (adapter._process.pid, adapter._process.pid)
    adapter.cancel()


def test_reused_command_cannot_replace_retained_process_before_verified_release(tmp_path, monkeypatch):
    adapter = CommandAgentAdapter([sys.executable, "-c", "print('complete')"])
    old_releases, new_releases, launches = [], [], []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        launches.append(process)
        return process

    adapter.set_process_released(lambda *identity: old_releases.append(identity))
    monkeypatch.setattr(subprocess, "Popen", launch)
    with monkeypatch.context() as cleanup_patch:
        cleanup_patch.setattr(adapter, "_cleanup_owned_process", lambda *_: False)
        with pytest.raises(AgentInvocationError, match="cleanup could not be confirmed"):
            adapter.run(request(tmp_path / "first"))
        retained = adapter._process
        adapter.set_process_released(lambda *identity: new_releases.append(identity))
        with pytest.raises(AgentInvocationError, match="cleanup could not be confirmed"):
            adapter.run(request(tmp_path / "second"))
        assert adapter._process is retained
        assert len(launches) == 1
        assert not (tmp_path / "second").exists()
        assert old_releases == new_releases == []
    assert adapter.run(request(tmp_path / "third")).text == "complete"
    assert len(launches) == 2
    assert old_releases == [(retained.pid, retained.pid)]
    assert new_releases == [(launches[1].pid, launches[1].pid)]
    assert adapter.process_info() == (None, None)


def test_active_legacy_command_cannot_be_overwritten_by_concurrent_run(tmp_path):
    adapter = CommandAgentAdapter([sys.executable, "-c", "import time; time.sleep(30)"])
    started = threading.Event()
    adapter.set_process_observer(lambda *_: started.set())
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(adapter.run, request(tmp_path / "first"))
        try:
            assert started.wait(3)
            identity = adapter.process_info()
            with pytest.raises(AgentInvocationError, match="active invocation"):
                adapter.run(request(tmp_path / "second"))
            assert adapter.process_info() == identity and not active.done()
            assert not (tmp_path / "second").exists()
        finally:
            adapter.cancel()
            with pytest.raises(AgentInvocationError):
                active.result(timeout=3)


def test_command_cleanup_retries_transient_permission_probe_after_term(tmp_path, monkeypatch):
    adapter = CommandAgentAdapter([sys.executable, "-c", "import time; time.sleep(30)"])
    killpg = os.killpg
    term_sent = False
    injected = False

    def probe(pgid, sig):
        nonlocal term_sent, injected
        if sig == signal.SIGTERM:
            term_sent = True
        if sig == 0 and term_sent and not injected:
            injected = True
            raise PermissionError("transient group probe")
        return killpg(pgid, sig)

    def observer(*_):
        raise RuntimeError("ownership rejected")

    adapter.set_process_observer(observer)
    monkeypatch.setattr(os, "killpg", probe)
    with pytest.raises(RuntimeError, match="ownership rejected"):
        adapter.run(request(tmp_path))
    assert injected and adapter.process_info() == (None, None)


@pytest.mark.parametrize("keep_pipes", [True, False])
def test_command_cleans_descendants_after_leader_exit(tmp_path, keep_pipes):
    redirects = "" if keep_pipes else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    command = (
        "import json,pathlib,subprocess,sys; r=json.load(sys.stdin); "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']"
        f"{redirects}); "
        "pathlib.Path(r['workspace'],'child').write_text(str(child.pid)); "
        "print(json.dumps({'text':'complete'}),flush=True)"
    )
    # Exercise a real early-exiting leader inside an independent wrapper. On Linux the
    # wrapper becomes a subreaper and reaps only the known descendant, so this fixture
    # neither depends on PID 1's zombie policy nor changes pytest's process semantics.
    wrapper = textwrap.dedent("""\
        import ctypes,json,os,signal,sys,threading,time
        from pathlib import Path
        from famou.agents import AgentRequest,CommandAgentAdapter
        workspace = Path(sys.argv[1])
        reaper = None
        if sys.platform.startswith('linux'):
            assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
            def reap_descendant():
                deadline = time.monotonic() + 5
                child_path = workspace / 'child'
                while time.monotonic() < deadline:
                    try:
                        pid = int(child_path.read_text())
                        os.waitpid(pid, 0)
                        return
                    except (FileNotFoundError, ValueError, ChildProcessError):
                        time.sleep(0.005)
            reaper = threading.Thread(target=reap_descendant, daemon=True)
            reaper.start()
        adapter = CommandAgentAdapter([sys.executable, '-c', sys.argv[2]])
        observed,released = [],[]
        adapter.set_process_observer(lambda *args: observed.append(args))
        adapter.set_process_released(lambda *args: released.append(args))
        watchdog = threading.Timer(4, adapter.cancel)
        watchdog.daemon = True
        watchdog.start()
        started = time.monotonic()
        try:
            result = adapter.run(AgentRequest('run','task','worker','work',workspace=workspace))
            assert result.text == 'complete'
            assert time.monotonic() - started < 3
            assert observed == released and len(released) == 1
            try:
                os.killpg(observed[0][1],0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('process group still alive')
            print(json.dumps({'text':result.text,'released':len(released)}))
        finally:
            watchdog.cancel()
            adapter.cancel()
            if reaper is not None:
                reaper.join(timeout=2)
    """)
    result = subprocess.run(
        [sys.executable, "-c", wrapper, str(tmp_path), command],
        capture_output=True, text=True, timeout=8, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"text": "complete", "released": 1}
