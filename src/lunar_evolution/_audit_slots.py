"""Read-only uniqueness checks for retained native candidate execution slots."""
from __future__ import annotations

import os
import re
import stat
import sys

from ._benchmark_files import absolute_path
from ._candidate_workspace_io import DirectoryChain, identity

_RUN = re.compile(r"\.bundle-run-[0-9a-f]{24}")
_EVALUATION = re.compile(r"\.candidate-evaluation-[0-9a-f]{24}")
_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class _SlotProblem(ValueError):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def _fail(reason, status="failed"):
    raise _SlotProblem(status, reason) from None


def _paths(plan, admission, execution, evaluation, cleanup):
    # Shape matching rejects absolute, dot, traversal and alternate separators.
    if any(type(value) is not str or len(value) > 512
           for value in (plan, admission, execution, evaluation)):
        _fail("slot_request_invalid")
    match = re.fullmatch(r"evolution/bundle-attempts/(\.bundle-run-[0-9a-f]{24})/plan\.json", plan)
    if match is None:
        _fail("slot_request_invalid")
    run_name = match[1]
    prefix = "evolution/bundle-attempts/" + run_name
    if admission != prefix + "/admission.json" or execution != prefix + "/attempt":
        _fail("slot_request_invalid")
    if cleanup is not None and cleanup != prefix + "/attempt/cleanup.json":
        _fail("slot_request_invalid")
    if not evaluation.startswith(prefix + "/evaluations/"):
        _fail("slot_request_invalid")
    evaluation_name = evaluation.removeprefix(prefix + "/evaluations/")
    if _EVALUATION.fullmatch(evaluation_name) is None:
        _fail("slot_request_invalid")
    return run_name, evaluation_name


def _directory_state(descriptor):
    info = os.fstat(descriptor)
    return (*identity(info), info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def _one_directory(chain, expected, pattern):
    """At most two entries are examined: a second entry already violates the slot."""
    chain.check()
    before = _directory_state(chain.fd)
    seen = []
    with os.scandir(chain.fd) as entries:
        for entry in entries:
            if seen:
                _fail("slot_extra_attempt")
            if entry.name != expected or pattern.fullmatch(entry.name) is None:
                _fail("slot_extra_attempt")
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                _fail("slot_entry_unsafe")
            seen.append((entry.name, identity(info)))
    if not seen:
        _fail("slot_missing", "unverifiable")
    if before != _directory_state(chain.fd):
        _fail("slot_changed", "unverifiable")
    chain.check()
    return seen[0][1]


def _regular(chain, name):
    before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        _fail("slot_entry_unsafe")
    descriptor = os.open(name, _FLAGS, dir_fd=chain.fd)
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or identity(before) != identity(opened) or identity(opened) != identity(named):
            _fail("slot_changed", "unverifiable")
        return identity(opened)
    finally:
        os.close(descriptor)


def _inspect(child_workspace, plan_path, admission_path, execution_path, evaluation_path, cleanup_path):
    run_name, evaluation_name = _paths(
        plan_path, admission_path, execution_path, evaluation_path, cleanup_path,
    )
    child = absolute_path(child_workspace)
    held = []

    def hold(path):
        chain = DirectoryChain(path, "audit_slot_root_changed")
        held.append(chain)
        return chain

    try:
        hold(child)
        attempts = hold(child / "evolution" / "bundle-attempts")
        run_identity = _one_directory(attempts, run_name, _RUN)
        run_path = child / "evolution" / "bundle-attempts" / run_name
        run = hold(run_path)
        if identity(os.fstat(run.fd)) != run_identity:
            _fail("slot_changed", "unverifiable")
        files = {name: _regular(run, name) for name in ("plan.json", "admission.json")}
        attempt = hold(run_path / "attempt")
        if cleanup_path is not None:
            _regular(attempt, "cleanup.json")
        evaluations = hold(run_path / "evaluations")
        evaluation_identity = _one_directory(evaluations, evaluation_name, _EVALUATION)
        evaluation = hold(run_path / "evaluations" / evaluation_name)
        if identity(os.fstat(evaluation.fd)) != evaluation_identity:
            _fail("slot_changed", "unverifiable")
        if (_one_directory(attempts, run_name, _RUN) != run_identity
                or _one_directory(evaluations, evaluation_name, _EVALUATION) != evaluation_identity
                or {name: _regular(run, name) for name in files} != files):
            _fail("slot_changed", "unverifiable")
        for chain in held:
            chain.check()
    finally:
        # Release every descriptor even if a later close fails or execution is interrupted.
        active = sys.exception()
        failure = None
        for chain in reversed(held):
            try:
                chain.close()
            except BaseException as exc:  # noqa: BLE001 - release remaining owned handles
                if failure is None or isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    failure = exc
        if failure is not None and not isinstance(active, (KeyboardInterrupt, SystemExit)):
            raise failure


def audit_execution_slots(
    child_workspace, *, plan_path, admission_path, execution_path, evaluation_path,
    cleanup_path=None,
):
    """Report one run directory and one evaluation directory, never executing files.

    Paths must name native plan/admission/attempt/evaluation locations under one
    ``evolution/bundle-attempts/.bundle-run-*`` directory. Even an extra empty or
    failed attempt is rejected. Missing evidence remains unverifiable. This is
    a uniqueness check; the native inspectors still validate each record's bytes.
    """
    try:
        _inspect(child_workspace, plan_path, admission_path, execution_path, evaluation_path, cleanup_path)
    except _SlotProblem as exc:
        return {"status": exc.status, "reason": exc.reason}
    except FileNotFoundError:
        return {"status": "unverifiable", "reason": "slot_missing"}
    except (OSError, TypeError, ValueError, RuntimeError):
        return {"status": "unverifiable", "reason": "slot_unverifiable"}
    return {"status": "verified", "reason": None}


__all__ = ["audit_execution_slots"]
