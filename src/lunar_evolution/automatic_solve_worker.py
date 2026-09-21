"""Private detached coordinator: transfer an existing owner before admitting work."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .automatic_solve_lifecycle import AutomaticSolveAlreadyRunning, own_automatic_solve
from .config import Config
from .controller import LocalController
from .process_ownership import RegisteredProcess
from .runtime import MockRuntime
from .store import Store

_TERMINAL = {"succeeded", "failed", "cancelled"}


def _runner_exited(pid: int | None) -> bool:
    if type(pid) is not int or pid <= 1:
        raise ValueError("invalid automatic solve runner identity")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError as exc:
        raise ValueError("automatic solve runner liveness is unknown") from exc
    return False


def _valid_process_identity(pid, pgid) -> bool:
    return all(type(value) is int and value > 1 for value in (pid, pgid))


def _owned_runner(store, run_id: str, pid: int, pgid: int) -> bool:
    current = store.get_run(run_id)
    return current is not None and (current.runner_pid, current.runner_pgid) == (pid, pgid)


def prepare_automatic_continuation(controller, run) -> None:
    """Under the workspace lock, recover only after all old owned work is released."""
    from .automatic_solve_bundle import validate_automatic_preparation_recovery

    store = controller.store
    run = store.get_run(run.id) or run
    if run.status.value in _TERMINAL:
        return
    validate_automatic_preparation_recovery(store, run.id)
    scope = controller._automatic_cancel_targets(run.id)
    if scope is None or not scope.verified:
        raise ValueError("automatic solve process ownership cannot be verified")
    for run_id in (run.id, scope.child_id):
        if run_id is None:
            continue
        current = store.get_run(run_id)
        if (current is not None and (current.runner_pid, current.runner_pgid) != (None, None)
                and not _valid_process_identity(current.runner_pid, current.runner_pgid)):
            raise ValueError("invalid automatic solve runner identity")
        for registration in store.list_attempt_processes(run_id):
            if not _valid_process_identity(registration["pid"], registration["pgid"]):
                raise ValueError("invalid automatic solve attempt identity")
    # A newly claimed worker already owns this exact registration. It has not started
    # an execution yet; all other coordinators must be proven gone before recovery.
    for registration in scope.targets:
        if not registration.label.startswith("run:"):
            continue
        if (registration.label == f"run:{run.id}"
                and (registration.pid, registration.pgid) == (os.getpid(), os.getpgrp())):
            continue
        if not _runner_exited(registration.pid):
            raise AutomaticSolveAlreadyRunning("automatic solve runner is still alive")
    controller.cleanup_automatic_solve(run.id)
    remaining = controller._automatic_cancel_targets(run.id)
    if remaining is None or not remaining.verified or any(
        not (reg.label == f"run:{run.id}" and
             (reg.pid, reg.pgid) == (os.getpid(), os.getpgrp()))
        for reg in remaining.targets
    ):
        raise ValueError("automatic solve owned process cleanup is incomplete")
    for run_id in (run.id, scope.child_id):
        if run_id is None:
            continue
        current = store.get_run(run_id)
        if (store.list_attempt_processes(run_id)
                or current is not None and (current.runner_pid, current.runner_pgid) != (None, None)
                and not (run_id == run.id and _owned_runner(store, run_id, os.getpid(), os.getpgrp()))):
            raise ValueError("automatic solve owned process cleanup is incomplete")
    # Intake can have been interrupted before any contract exists. Its old attempt
    # must become retryable; child evolution retains its existing recovery rules.
    latest = store.get_run(run.id)
    if latest is not None and latest.status.value not in _TERMINAL:
        store.recover_running(run.id)


def launch_automatic_solve(config, args, controller, run, owner) -> None:
    """Spawn while holding the reservation, register once, then open the work gate."""
    from .cli import _automatic_runtime_command

    if owner.parent_id != run.id or owner.lock_fd is None:
        raise ValueError("detached automatic solve requires workspace ownership")
    store = controller.store
    gate_read, gate_write = os.pipe()
    process = None
    registered = False
    try:
        command = [
            sys.executable, "-m", "lunar_evolution.automatic_solve_worker",
            "--home", str(config.home), "--run-id", run.id,
            "--lock-fd", str(owner.lock_fd), "--gate-fd", str(gate_read), "--",
            *_automatic_runtime_command(config, args, run),
        ]
        env = os.environ.copy()
        if args.api_key is not None:
            env["LUNAR_EVOLUTION_API_KEY"] = args.api_key
        with (run.workspace / "controller.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=Path.cwd(), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                close_fds=True, pass_fds=(owner.lock_fd, gate_read), env=env,
            )
        os.close(gate_read)
        gate_read = None
        # start_new_session makes the new child its own process-group leader.
        registered = store.claim_runner_process(run.id, process.pid, process.pid)
        if not registered:
            raise ValueError("automatic solve launch lost execution admission")
        latest = store.get_run(run.id)
        if (latest is None or latest.status.value in _TERMINAL
                or store.pending_input(run.id) is not None):
            raise ValueError("automatic solve stopped during launch")
        if os.write(gate_write, b"1") != 1:
            raise ValueError("automatic solve launch gate was not accepted")
        # No parent registration writes after the gate: even an instant child exit
        # cannot be overwritten with a stale PID by the late launcher.
    except Exception as exc:  # All launcher failures must reap the exact child.
        if gate_write is not None:
            os.close(gate_write)
            gate_write = None
        if process is not None:
            # Before permission the child cannot have started model or local work.
            # Reap this exact child, never an unrelated identity from the database.
            try:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass  # The exact child exited between poll and signal.
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
            except Exception:  # noqa: BLE001, S110 - keep unresolved ownership and original error
                pass
            if process.poll() is not None:
                try:
                    # Also covers a Store write which committed before raising.
                    store.clear_runner_process(run.id, process.pid, process.pid)
                except Exception:  # noqa: BLE001, S110 - a database outage must not mask launch failure
                    pass
        raise ValueError("could not start detached automatic solve; explicit resume is available") from exc
    finally:
        if gate_read is not None:
            os.close(gate_read)
        if gate_write is not None:
            os.close(gate_write)


def _validate_continuation(continuation, config, run_id) -> None:
    from .cli import build_parser

    args = build_parser().parse_args(continuation)
    if not (args.command == "solve" and args.resume and args.run_id == run_id
            and not args.detach and args.home is not None
            and Path(args.home).expanduser().resolve() == config.home):
        raise ValueError("automatic solve continuation does not match its owner")


def _cleanup_exiting_worker(config, store, run_id, pid, pgid) -> None:
    if not _owned_runner(store, run_id, pid, pgid):
        return
    cleanup = LocalController(config, MockRuntime(), store=store)
    scope = cleanup._automatic_cancel_targets(run_id)
    if scope is None or not scope.verified:
        return
    # Freeze this worker's registrations and recheck the coordinator on every signal.
    # A stale finalizer must never select or terminate a replacement worker's work.
    registrations = tuple(RegisteredProcess(
        reg.pid, reg.pgid,
        owner_check=lambda reg=reg: (
            _owned_runner(store, run_id, pid, pgid)
            and reg.owner_check is not None and reg.owner_check()
        ),
        label=reg.label,
    ) for reg in scope.targets)
    cleanup._cleanup_process_registrations(registrations)


def main(argv=None) -> int:
    """Internal entry point; public users continue through the ordinary CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--lock-fd", required=True, type=int)
    parser.add_argument("--gate-fd", required=True, type=int)
    parser.add_argument("continuation", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    config = Config.from_env(args.home)
    store = Store(config.database)
    pid, pgid = os.getpid(), os.getpgrp()
    gate = args.gate_fd
    lock_fd = args.lock_fd
    try:
        os.set_inheritable(gate, False)
        run = store.get_run(args.run_id)
        if run is None:
            return 2
        ownership = own_automatic_solve(run.id, run.workspace, inherited_fd=lock_fd)
        lock_fd = None  # The context also closes the inherited FD if __enter__ fails.
        with ownership as owner:
            try:
                allowed = os.read(gate, 1) == b"1"
            finally:
                os.close(gate)
                gate = None
            latest = store.get_run(run.id)
            if (not allowed or latest is None or latest.status.value in _TERMINAL
                    or (latest.runner_pid, latest.runner_pgid) != (pid, pgid)
                    or store.pending_input(run.id) is not None):
                return 0
            from .cli import main as cli_main

            continuation = args.continuation
            if continuation[:1] == ["--"]:
                continuation = continuation[1:]
            try:
                _validate_continuation(continuation, config, run.id)
                return cli_main(continuation, _automatic_owner=owner)
            finally:
                # Covers parsing/runtime validation failures and unexpected exceptions.
                # Cleanup stops registered local work before releasing the coordinator.
                _cleanup_exiting_worker(config, store, run.id, pid, pgid)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if gate is not None:
            os.close(gate)
        store.clear_runner_process(args.run_id, pid, pgid)


if __name__ == "__main__":
    raise SystemExit(main())
