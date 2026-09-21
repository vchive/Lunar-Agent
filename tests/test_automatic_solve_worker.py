"""Worker recovery and exit cleanup respect exact durable execution ownership."""
from __future__ import annotations

import os

import pytest

from lunar_evolution import automatic_solve_worker as worker
from lunar_evolution import cli
from lunar_evolution.automatic_solve_lifecycle import AutomaticSolveAlreadyRunning
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.models import TaskStatus
from lunar_evolution.runtime import MockRuntime


@pytest.fixture
def automatic(tmp_path):
    config = Config.from_env(tmp_path / "home")
    controller = LocalController(config, MockRuntime())
    run = controller.create_conversational_run("test automatic recovery", workspace=tmp_path / "run")
    run.workspace.mkdir(parents=True, exist_ok=True)
    controller.store.append_event(run.id, "evolution_requested", {
        "bundle_mode": "compiled", "automatic_lifecycle_version": 1,
    })
    return config, controller, run


def _pending_attempt(controller, run):
    task = controller.store.list_tasks(run.id)[0]
    attempt = controller.store.claim_task(task.id, "test")
    assert attempt is not None
    return task, attempt


@pytest.mark.parametrize("identity", [(101, None), (None, 201), ("bad", "bad"), (0, 0)])
def test_prepare_rejects_malformed_runner_before_cleanup(automatic, monkeypatch, identity):
    _, controller, run = automatic
    task, _ = _pending_attempt(controller, run)
    controller.store.set_runner_process(run.id, *identity)
    monkeypatch.setattr(controller, "cleanup_automatic_solve", lambda *_: pytest.fail("cleanup admitted"))
    with pytest.raises(ValueError, match="runner identity"):
        worker.prepare_automatic_continuation(controller, run)
    assert controller.store.get_task(task.id).state is TaskStatus.RUNNING


@pytest.mark.parametrize("identity", [(101, None), (None, 201), ("bad", "bad"), (0, 0)])
def test_prepare_rejects_malformed_attempt_before_cleanup(automatic, monkeypatch, identity):
    _, controller, run = automatic
    task, attempt = _pending_attempt(controller, run)
    controller.store.set_attempt_process(attempt.id, *identity)
    monkeypatch.setattr(controller, "cleanup_automatic_solve", lambda *_: pytest.fail("cleanup admitted"))
    with pytest.raises(ValueError, match="attempt identity"):
        worker.prepare_automatic_continuation(controller, run)
    assert controller.store.get_task(task.id).state is TaskStatus.RUNNING


@pytest.mark.parametrize("unknown", [False, True])
def test_live_or_unknown_runner_blocks_recovery(automatic, monkeypatch, unknown):
    _, controller, run = automatic
    task, _ = _pending_attempt(controller, run)
    controller.store.set_runner_process(run.id, 101, 201)

    def probe(*_):
        if unknown:
            raise PermissionError("not permitted to inspect")

    monkeypatch.setattr(worker.os, "kill", probe)
    monkeypatch.setattr(controller, "cleanup_automatic_solve", lambda *_: pytest.fail("cleanup admitted"))
    with pytest.raises(ValueError if unknown else AutomaticSolveAlreadyRunning):
        worker.prepare_automatic_continuation(controller, run)
    assert controller.store.get_task(task.id).state is TaskStatus.RUNNING


def test_recover_intake_only_after_stale_processes_are_released(automatic, monkeypatch):
    _, controller, run = automatic
    task, attempt = _pending_attempt(controller, run)
    controller.store.set_runner_process(run.id, 101, 201)
    controller.store.set_attempt_process(attempt.id, 301, 401)
    monkeypatch.setattr(worker, "_runner_exited", lambda _: True)

    def cleanup(run_id):
        assert run_id == run.id
        assert controller.store.get_task(task.id).state is TaskStatus.RUNNING
        controller.store.clear_attempt_process(attempt.id, 301, 401)
        controller.store.clear_runner_process(run.id, 101, 201)

    monkeypatch.setattr(controller, "cleanup_automatic_solve", cleanup)
    worker.prepare_automatic_continuation(controller, run)
    assert controller.store.get_task(task.id).state is TaskStatus.UNCERTAIN
    assert controller.store.get_attempt(attempt.id).status == "uncertain"
    assert controller.store.get_run(run.id).runner_pid is None


def test_unresolved_cleanup_does_not_recover_intake(automatic, monkeypatch):
    _, controller, run = automatic
    task, attempt = _pending_attempt(controller, run)
    controller.store.set_attempt_process(attempt.id, 301, 401)
    monkeypatch.setattr(controller, "cleanup_automatic_solve", lambda _: None)
    with pytest.raises(ValueError, match="cleanup is incomplete"):
        worker.prepare_automatic_continuation(controller, run)
    assert controller.store.get_task(task.id).state is TaskStatus.RUNNING


def _worker_args(config, controller, run, *, allowed=True, continuation=None):
    fd = os.open(run.workspace / ".automatic-solve.lock", os.O_CREAT | os.O_RDWR, 0o600)
    read, write = os.pipe()
    if allowed:
        os.write(write, b"1")
    os.close(write)
    controller.store.set_runner_process(run.id, os.getpid(), os.getpgrp())
    return [
        "--home", str(config.home), "--run-id", run.id, "--lock-fd", str(fd),
        "--gate-fd", str(read), "--", *(continuation if continuation is not None else [
            "solve", "--resume", "--run-id", run.id, "--home", str(config.home),
        ]),
    ], fd, read


def test_gate_eof_stops_without_runtime_and_releases_own_identity(automatic, monkeypatch):
    config, controller, run = automatic
    args, lock_fd, gate_fd = _worker_args(config, controller, run, allowed=False)
    closed = []
    original_close = os.close

    def close(fd):
        closed.append(fd)
        original_close(fd)

    monkeypatch.setattr(worker.os, "close", close)
    monkeypatch.setattr(cli, "main", lambda *_a, **_k: pytest.fail("runtime admitted"))
    assert worker.main(args) == 0
    assert controller.store.get_run(run.id).runner_pid is None
    # SQLite may already have reused a closed numeric FD during final Store writes.
    assert lock_fd in closed and gate_fd in closed


@pytest.mark.parametrize("mismatch", ["home", "run", "detach", "missing_home"])
def test_private_continuation_must_match_owned_run_and_home(automatic, monkeypatch, mismatch):
    config, controller, run = automatic
    continuation = ["solve", "--resume", "--run-id", "other" if mismatch == "run" else run.id]
    if mismatch != "missing_home":
        continuation += ["--home", str(config.home / "other" if mismatch == "home" else config.home)]
    if mismatch == "detach":
        continuation += ["--detach"]
    args, _, _ = _worker_args(config, controller, run, continuation=continuation)
    monkeypatch.setattr(cli, "main", lambda *_a, **_k: pytest.fail("runtime admitted"))
    with pytest.raises(ValueError, match="does not match"):
        worker.main(args)
    assert controller.store.get_run(run.id).runner_pid is None
    assert not (config.home / "other").exists()


def test_late_worker_finalizer_never_cleans_replacement(automatic, monkeypatch):
    config, controller, run = automatic
    args, _, _ = _worker_args(config, controller, run)

    def replace(*_args, **_kwargs):
        controller.store.set_runner_process(run.id, 501, 601)
        return 0

    monkeypatch.setattr(cli, "main", replace)
    monkeypatch.setattr(worker, "LocalController", lambda *_a, **_k: pytest.fail("replacement cleanup admitted"))
    assert worker.main(args) == 0
    latest = controller.store.get_run(run.id)
    assert (latest.runner_pid, latest.runner_pgid) == (501, 601)


def test_finalizer_snapshot_revokes_each_signal_if_runner_replaced(automatic, monkeypatch):
    config, controller, run = automatic
    _, attempt = _pending_attempt(controller, run)
    pid, pgid = os.getpid(), os.getpgrp()
    controller.store.set_runner_process(run.id, pid, pgid)
    controller.store.set_attempt_process(attempt.id, 301, 401)
    calls = []

    def cleanup(registrations):
        assert registrations
        controller.store.set_runner_process(run.id, 501, 601)
        calls.extend(reg.owner_check() for reg in registrations)

    monkeypatch.setattr(worker, "LocalController", lambda *_a, **_k: controller)
    monkeypatch.setattr(controller, "_cleanup_process_registrations", cleanup)
    worker._cleanup_exiting_worker(config, controller.store, run.id, pid, pgid)
    assert calls and not any(calls)
    latest = controller.store.get_run(run.id)
    assert (latest.runner_pid, latest.runner_pgid) == (501, 601)


def test_worker_cancellation_after_gate_prevents_runtime(automatic, monkeypatch):
    config, controller, run = automatic
    args, _, _ = _worker_args(config, controller, run)
    controller.store.cancel_run(run.id)
    monkeypatch.setattr(cli, "main", lambda *_a, **_k: pytest.fail("runtime admitted"))
    assert worker.main(args) == 0
    assert controller.store.get_run(run.id).runner_pid is None
