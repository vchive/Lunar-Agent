"""Tracked subprocesses release ownership only after their entire private group exits."""
from __future__ import annotations

import errno
import os
import signal
import sys
import time

import pytest

from famou import candidate_execution_runner as runner


def _run(tmp_path, *, tracked=True, code="print('done')", released=None):
    return runner._bounded_process_bytes(
        [sys.executable, "-c", code], cwd=str(tmp_path), environment={}, timeout=2,
        output_limit=1024, capture_limit=1024,
        process_observer=(lambda pid, pgid: None) if tracked else None,
        process_released=released,
    )


def test_tracked_process_waits_for_group_confirmation_before_release(tmp_path, monkeypatch):
    killpg = os.killpg
    observations = []

    def group_probe(pgid, sig):
        if sig != 0:
            return killpg(pgid, sig)
        observations.append(pgid)
        if len(observations) == 1:
            return None
        if len(observations) == 2:
            raise PermissionError(errno.EPERM, "fixture group still retiring")
        raise ProcessLookupError(errno.ESRCH, "fixture group gone")

    monkeypatch.setattr(runner.os, "killpg", group_probe)
    released = []
    result = _run(tmp_path, released=lambda pid, pgid: released.append((pid, pgid, len(observations))))

    assert result[2:] == ("succeeded", 0, None)
    assert len(released) == 1
    assert released[0][2] == 3


@pytest.mark.parametrize("observation", ["present", "permission", "probe_failure"])
@pytest.mark.parametrize("overflow", [False, True])
def test_unconfirmed_group_retains_registration_and_fails(tmp_path, monkeypatch, observation, overflow):
    killpg = os.killpg

    def group_probe(pgid, sig):
        if sig != 0:
            return killpg(pgid, sig)
        if observation == "permission":
            raise PermissionError(errno.EPERM, "fixture")
        if observation == "probe_failure":
            raise OSError(errno.EIO, "fixture")
        return None

    monkeypatch.setattr(runner.os, "killpg", group_probe)
    monkeypatch.setattr(runner, "PROCESS_CLEANUP_GRACE_SECONDS", 0.05)
    released = []
    code = "print('x' * 2048)" if overflow else "print('done')"
    result = _run(tmp_path, code=code, released=lambda *args: released.append(args))

    assert result[2] == "failed"
    assert result[4] == "process_cleanup_failed"
    assert released == []


def test_legacy_process_does_not_add_group_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_wait_owned_group_exit", lambda *_: pytest.fail("legacy group probe"))
    assert _run(tmp_path, tracked=False)[2:] == ("succeeded", 0, None)


@pytest.mark.parametrize("pid,pgid", [(1, 1), (321, None), (321, 322)])
def test_group_exit_probe_rejects_nonprivate_identity(monkeypatch, pid, pgid):
    monkeypatch.setattr(runner.os, "killpg", lambda *_: pytest.fail("invalid group probed"))
    assert not runner._wait_owned_group_exit(pid, pgid)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("inherit_pipes", [False, True])
def test_real_descendant_cleanup_is_confirmed_before_release(tmp_path, inherit_pipes):
    redirects = "" if inherit_pipes else ",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL"
    code = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']{redirects}); "
        "print(child.pid,flush=True)"
    )
    observed = []
    released = []

    def release(pid, pgid):
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)
        released.append((pid, pgid))

    started = time.monotonic()
    try:
        result = runner._bounded_process_bytes(
            [sys.executable, "-c", code], cwd=str(tmp_path), environment={}, timeout=2,
            output_limit=1024, capture_limit=1024,
            process_observer=lambda pid, pgid: observed.append((pid, pgid)),
            process_released=release,
        )
        assert time.monotonic() - started < 1.5
        assert observed and observed[0][0] == observed[0][1]
        if result[2] == "succeeded":
            assert released == observed
        else:
            # PID 1 may leave a killed orphan unreaped: keep ownership and report uncertainty
            # rather than making a machine-specific promise that the group disappeared.
            assert result[2] == "failed" and result[4] == "process_cleanup_failed"
            assert released == []
    finally:
        for _, pgid in observed:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
