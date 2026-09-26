from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution.process_ownership import (
    ProcessCleanupResult,
    ProcessCleanupStatus,
    cleanup_registered_process,
)
from lunar_evolution.producer_bootstrap import (
    TrustedBootstrapEvidence,
    TrustedBootstrapLaunch,
    parse_trusted_bootstrap_registration,
)
from lunar_evolution.trusted_bootstrap_runtime import (
    TrustedBootstrapRuntimeError,
    build_trusted_bootstrap_descriptor,
    recover_trusted_bootstrap_fixture,
    run_trusted_bootstrap_fixture,
)

DIGEST = "a" * 64


def _target(tmp_path: Path, *, name: str = "target.py") -> Path:
    path = tmp_path / name
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "Path('target-marker').write_text('started', encoding='utf-8')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _exiting_target(tmp_path: Path, code: int) -> Path:
    path = tmp_path / f"exit-{code}.py"
    path.write_text(f"#!/usr/bin/env python3\nraise SystemExit({code})\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _sleeping_target(tmp_path: Path) -> Path:
    path = tmp_path / "sleep.py"
    path.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(2)\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _descendant_target(tmp_path: Path) -> Path:
    path = tmp_path / "descendant.py"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import signal, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)'])\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _launch(target: Path, *, bootstrap=None) -> TrustedBootstrapLaunch:
    target_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    descriptor = bootstrap or build_trusted_bootstrap_descriptor()
    return TrustedBootstrapLaunch(
        launch_id="launch-001",
        journal_id="journal-001",
        run_id="run-001",
        parent_task_id="parent-001",
        task_id="task-001",
        intent_sha256=DIGEST,
        attestation_sha256=DIGEST,
        bootstrap_descriptor_sha256=descriptor.descriptor_sha256 or descriptor.digest(),
        target_executable_identity=target_sha,
        gate_protocol="fd-read-one-byte-v1",
        gate_nonce="nonce-001",
    )


def _fixture_evidence_path(workspace: Path, launch: TrustedBootstrapLaunch) -> Path:
    return workspace / "evolution" / "producer-batches" / launch.journal_id / "trusted-bootstrap-evidence.json"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _start_child_fixture(
    tmp_path: Path, target: Path, *, launch: TrustedBootstrapLaunch | None = None,
):
    import lunar_evolution.trusted_bootstrap_runtime as runtime

    descriptor = build_trusted_bootstrap_descriptor()
    launch = launch or _launch(target)
    launch_read, launch_write = os.pipe()
    gate_read, gate_write = os.pipe()
    frame_read, frame_write = os.pipe()
    source_root = str(Path(runtime.__file__).resolve().parents[1])
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lunar_evolution.trusted_bootstrap_runtime",
            "--child",
            str(launch_read),
            str(gate_read),
            str(frame_write),
        ],
        start_new_session=True,
        close_fds=True,
        pass_fds=(launch_read, gate_read, frame_write),
        env={"PATH": os.defpath, "LANG": "C", "PYTHONPATH": source_root},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for fd in (launch_read, gate_read, frame_write):
        os.close(fd)
    control = {
        "launch": launch.to_dict(),
        "descriptor": descriptor.to_dict(),
        "target_executable": str(target.resolve()),
        "target_argv": [str(target.resolve())],
        "target_cwd": str(tmp_path.resolve()),
    }
    os.write(launch_write, runtime._canonical(control))
    os.close(launch_write)
    frame_stream = os.fdopen(frame_read, "rb")
    ready = json.loads(frame_stream.readline().decode("utf-8"))
    assert ready["kind"] == "bootstrap_ready"
    return process, gate_write, frame_stream


def test_child_does_not_inspect_target_before_gate_release(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    target.unlink()
    process, gate_write, frames = _start_child_fixture(tmp_path, target, launch=launch)
    try:
        assert process.poll() is None
        os.write(gate_write, b"1")
        os.close(gate_write)
        gate_write = -1
        failure = json.loads(frames.readline().decode("utf-8"))
        assert failure["kind"] == "target_start_failed"
        assert process.wait(timeout=3) == 25
    finally:
        frames.close()
        if gate_write >= 0:
            os.close(gate_write)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
    assert not (tmp_path / "target-marker").exists()


def test_post_release_target_identity_failure_emits_start_failure(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    process, gate_write, frames = _start_child_fixture(tmp_path, target, launch=launch)
    hardlink = tmp_path / "target-hardlink.py"
    try:
        os.link(target, hardlink)
        os.write(gate_write, b"1")
        os.close(gate_write)
        gate_write = -1
        failure = json.loads(frames.readline().decode("utf-8"))
        assert failure["kind"] == "target_start_failed"
        assert process.wait(timeout=3) == 25
    finally:
        frames.close()
        if gate_write >= 0:
            os.close(gate_write)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
    assert not (tmp_path / "target-marker").exists()


def test_runtime_durably_registers_before_release_and_starts_target_after_gate(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    synced_inodes: set[tuple[int, int]] = set()
    registration_path: Path | None = None

    import lunar_evolution.trusted_bootstrap_runtime as runtime

    original_fsync = runtime.os.fsync

    def track_fsync(fd: int) -> None:
        info = os.fstat(fd)
        synced_inodes.add((info.st_dev, info.st_ino))
        original_fsync(fd)

    runtime.os.fsync = track_fsync
    try:
        def before_release(path: Path) -> None:
            nonlocal registration_path
            registration_path = path
            assert path.is_file()
            assert not (tmp_path / "target-marker").exists()
            info = path.stat()
            assert (info.st_dev, info.st_ino) in synced_inodes
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["registration_sha256"]
            parsed = parse_trusted_bootstrap_registration(payload, launch=launch)
            assert parsed.pid == payload["pid"]
            assert parsed.pgid == payload["pgid"]

        result = run_trusted_bootstrap_fixture(
            tmp_path,
            launch=launch,
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            on_before_release=before_release,
        )
    finally:
        runtime.os.fsync = original_fsync

    assert result.evidence.status == "passed"
    assert result.evidence.bootstrap_ready_observed is True
    assert result.evidence.release_observed is True
    assert result.evidence.target_started_observed is True
    assert result.target_pid and result.target_pgid == result.bootstrap_pgid
    assert result.target_exit_code == 0
    assert registration_path is not None
    assert (tmp_path / "target-marker").read_text(encoding="utf-8") == "started"


def test_target_replacement_after_registration_is_failed_closed(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)

    def replace_target(_registration: Path) -> None:
        replacement = tmp_path / "replacement.py"
        replacement.write_text(
            "#!/usr/bin/env python3\nfrom pathlib import Path\nPath('target-marker').write_text('bad')\n",
            encoding="utf-8",
        )
        replacement.chmod(0o755)
        replacement.replace(target)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=launch,
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            on_before_release=replace_target,
        )
    assert exc.value.code == "producer_bootstrap_target_start_failed"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "failed"
    assert not (tmp_path / "target-marker").exists()


def test_target_exit_code_is_reported_without_downgrading_handshake(tmp_path: Path):
    target = _exiting_target(tmp_path, 7)
    result = run_trusted_bootstrap_fixture(
        tmp_path,
        launch=_launch(target),
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    assert result.evidence.status == "passed"
    assert result.target_exit_code == 7


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_successful_target_cleanup_removes_same_group_descendant(tmp_path: Path):
    target = _descendant_target(tmp_path)
    result = run_trusted_bootstrap_fixture(
        tmp_path,
        launch=_launch(target),
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    assert result.evidence.status == "passed"
    assert result.target_exit_code == 0
    with pytest.raises(ProcessLookupError):
        os.killpg(result.bootstrap_pgid, 0)


def test_bootstrap_registration_requires_os_start_identity(monkeypatch: pytest.MonkeyPatch):
    import lunar_evolution.trusted_bootstrap_runtime as runtime

    monkeypatch.setattr(runtime, "_process_owner_identity", lambda _pid: None)
    process = SimpleNamespace(pid=999991)
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        runtime._registered_bootstrap_process(process, process.pid, "launch-001")
    assert exc.value.code == "trusted_bootstrap_owner_identity_unknown"


@pytest.mark.parametrize("observed", [None, {"kind": "test", "pid": 999991, "start": 2}])
def test_bootstrap_cleanup_refuses_unreadable_or_drifted_live_identity(
    monkeypatch: pytest.MonkeyPatch, observed: object,
):
    import lunar_evolution.process_ownership as ownership
    import lunar_evolution.trusted_bootstrap_runtime as runtime
    from lunar_evolution import producer_process

    original = {"kind": "test", "pid": 999991, "start": 1}
    state = {"identity": original}
    monkeypatch.setattr(runtime, "_process_owner_identity", lambda _pid: state["identity"])
    monkeypatch.setattr(producer_process, "_process_owner_identity", lambda _pid: state["identity"])
    process = SimpleNamespace(pid=999991, poll=lambda: None)
    registration = runtime._registered_bootstrap_process(process, process.pid, "launch-001")
    state["identity"] = observed
    monkeypatch.setattr(ownership.os, "getpgid", lambda _pid: process.pid)

    def no_signal(_pgid: int, signal_number: int) -> None:
        if signal_number != 0:
            pytest.fail("identity drift must prevent a group signal")

    monkeypatch.setattr(ownership.os, "killpg", no_signal)
    result = cleanup_registered_process(registration)
    assert result.status == ProcessCleanupStatus.OWNERSHIP_LOST
    assert result.term_sent is False
    assert result.kill_sent is False


def test_bootstrap_cleanup_rechecks_identity_before_sigkill(monkeypatch: pytest.MonkeyPatch):
    import lunar_evolution.process_ownership as ownership
    import lunar_evolution.trusted_bootstrap_runtime as runtime
    from lunar_evolution import producer_process

    original = {"kind": "test", "pid": 999991, "start": 1}
    drifted = {"kind": "test", "pid": 999991, "start": 2}
    observations = iter([original, drifted])
    monkeypatch.setattr(runtime, "_process_owner_identity", lambda _pid: original)
    monkeypatch.setattr(producer_process, "_process_owner_identity", lambda _pid: next(observations))
    process = SimpleNamespace(pid=999991, poll=lambda: None)
    registration = runtime._registered_bootstrap_process(process, process.pid, "launch-001")
    monkeypatch.setattr(ownership.os, "getpgid", lambda _pid: process.pid)
    signals: list[int] = []
    monkeypatch.setattr(ownership.os, "killpg", lambda _pgid, number: signals.append(number))
    clock = iter([0.0, 1.0])
    result = cleanup_registered_process(
        registration,
        grace_seconds=0.01,
        monotonic=lambda: next(clock),
    )
    assert result.status == ProcessCleanupStatus.OWNERSHIP_LOST
    assert result.term_sent is True
    assert result.kill_sent is False
    assert signals == [0, ownership.signal.SIGTERM, 0]


def test_unverified_cleanup_preserves_unknown_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import lunar_evolution.trusted_bootstrap_runtime as runtime

    target = _target(tmp_path)
    original_cleanup = runtime.cleanup_registered_process
    calls = 0

    def uncertain_then_retry(registration, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ProcessCleanupResult(
                label=registration.label,
                pid=registration.pid,
                pgid=registration.pgid,
                status=ProcessCleanupStatus.CLEANUP_UNVERIFIED,
                alive_after=True,
            )
        return original_cleanup(registration, **kwargs)

    monkeypatch.setattr(runtime, "cleanup_registered_process", uncertain_then_retry)
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=_launch(target),
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
        )
    assert calls == 2
    assert exc.value.code == "trusted_bootstrap_cleanup_unknown"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "unknown"
    evidence_path = tmp_path / "evolution/producer-batches/journal-001/trusted-bootstrap-evidence.json"
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["status"] == "unknown"


def test_exception_cleanup_never_direct_kills_unverified_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import lunar_evolution.trusted_bootstrap_runtime as runtime

    target = _target(tmp_path)
    registration: dict[str, int] = {}

    def uncertain_cleanup(record, **kwargs):
        registration["pgid"] = record.pgid
        return ProcessCleanupResult(
            label=record.label,
            pid=record.pid,
            pgid=record.pgid,
            status=ProcessCleanupStatus.OWNERSHIP_LOST,
            alive_after=True,
        )

    monkeypatch.setattr(runtime, "cleanup_registered_process", uncertain_cleanup)
    monkeypatch.setattr(
        runtime.subprocess.Popen,
        "kill",
        lambda _process: pytest.fail("unverified cleanup must not bypass owner checks"),
    )
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=_launch(target),
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            timeout_seconds=0.05,
            on_before_release=lambda _path: time.sleep(0.1),
        )
    assert exc.value.code == "trusted_bootstrap_deadline_exceeded"
    assert registration["pgid"] > 1
    try:
        os.killpg(registration["pgid"], 9)
    except ProcessLookupError:
        pass


@pytest.mark.parametrize(("gate_bytes", "expected_status"), [(b"11", 24), (b"", 24)])
def test_child_rejects_duplicate_gate_token_and_early_gate_eof(
    tmp_path: Path, gate_bytes: bytes, expected_status: int,
):
    target = _target(tmp_path)
    process, gate_write, frames = _start_child_fixture(tmp_path, target)
    try:
        if gate_bytes:
            os.write(gate_write, gate_bytes)
        os.close(gate_write)
        assert process.wait(timeout=3) == expected_status
    finally:
        frames.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    assert not (tmp_path / "target-marker").exists()


def test_runtime_deadline_expires_before_release_and_keeps_evidence_unknown(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)

    def wait_past_deadline(_registration: Path) -> None:
        time.sleep(0.1)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=launch,
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            timeout_seconds=0.05,
            on_before_release=wait_past_deadline,
        )
    assert exc.value.code == "trusted_bootstrap_deadline_exceeded"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "unknown"
    assert exc.value.evidence.release_observed is False
    assert not (tmp_path / "target-marker").exists()


def test_runtime_deadline_after_target_start_keeps_handshake_unknown(tmp_path: Path):
    target = _sleeping_target(tmp_path)
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=_launch(target),
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            timeout_seconds=1.0,
        )
    assert exc.value.code == "trusted_bootstrap_deadline_exceeded"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "unknown"
    assert exc.value.evidence.target_started_observed is True


def test_runtime_deadline_after_terminal_persists_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import lunar_evolution.trusted_bootstrap_runtime as runtime

    target = _target(tmp_path)
    original_remaining = runtime._remaining
    calls = 0

    def expire_after_terminal(deadline: float) -> float:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TrustedBootstrapRuntimeError("trusted_bootstrap_deadline_exceeded")
        return original_remaining(deadline)

    monkeypatch.setattr(runtime, "_remaining", expire_after_terminal)
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=_launch(target),
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
        )
    assert calls == 2
    assert exc.value.code == "trusted_bootstrap_deadline_exceeded"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "unknown"
    assert exc.value.evidence.target_started_observed is True
    evidence_path = tmp_path / "evolution/producer-batches/journal-001/trusted-bootstrap-evidence.json"
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["status"] == "unknown"


def test_fixture_recovery_returns_bound_terminal_evidence_without_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import lunar_evolution.trusted_bootstrap_runtime as runtime

    target = _target(tmp_path)
    launch = _launch(target)
    result = run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    assert Path(result.registration_path).name == "trusted-bootstrap-registration.json"
    Path(result.registration_path).with_name("process-registration.json").write_text(
        "{}", encoding="utf-8",
    )
    evidence_path = _fixture_evidence_path(tmp_path, launch)
    before = evidence_path.read_bytes()

    def prohibit_spawn(*_args: object, **_kwargs: object) -> None:
        pytest.fail("fixture recovery must not spawn a process")

    monkeypatch.setattr(runtime.subprocess, "Popen", prohibit_spawn)
    recovered = recover_trusted_bootstrap_fixture(tmp_path, launch=launch)

    assert recovered == {
        "status": "evidence_available",
        "bootstrap_status": "passed",
        "journal_id": launch.journal_id,
        "launch_id": launch.launch_id,
        "registration_sha256": result.registration_sha256,
        "evidence_sha256": result.evidence.evidence_sha256,
        "pid": result.bootstrap_pid,
        "pgid": result.bootstrap_pgid,
    }
    assert evidence_path.read_bytes() == before


def test_fixture_recovery_requires_registration_when_no_attempt_was_durable(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)

    recovered = recover_trusted_bootstrap_fixture(tmp_path, launch=launch)

    assert recovered == {
        "status": "recovery_required",
        "reason": "trusted_bootstrap_registration_missing",
        "journal_id": launch.journal_id,
        "launch_id": launch.launch_id,
    }


def test_fixture_recovery_requires_terminal_evidence_after_registration(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    _fixture_evidence_path(tmp_path, launch).unlink()

    recovered = recover_trusted_bootstrap_fixture(tmp_path, launch=launch)

    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "trusted_bootstrap_terminal_evidence_missing"
    assert recovered["journal_id"] == launch.journal_id
    assert recovered["launch_id"] == launch.launch_id


def test_fixture_recovery_returns_authenticated_failed_terminal_evidence(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=launch,
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            on_before_release=lambda _registration: target.unlink(),
        )
    assert exc.value.code == "producer_bootstrap_target_start_failed"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "failed"

    recovered = recover_trusted_bootstrap_fixture(tmp_path, launch=launch)

    assert recovered["status"] == "evidence_available"
    assert recovered["bootstrap_status"] == "failed"
    assert recovered["registration_sha256"] == exc.value.evidence.registration_sha256


def test_fixture_recovery_requires_manual_resolution_for_unknown_evidence(tmp_path: Path):
    target = _sleeping_target(tmp_path)
    launch = _launch(target)
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=launch,
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            timeout_seconds=1.0,
        )
    assert exc.value.code == "trusted_bootstrap_deadline_exceeded"
    assert exc.value.evidence is not None
    assert exc.value.evidence.status == "unknown"

    recovered = recover_trusted_bootstrap_fixture(tmp_path, launch=launch)

    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "trusted_bootstrap_evidence_unknown"
    assert recovered["journal_id"] == launch.journal_id
    assert recovered["launch_id"] == launch.launch_id


def test_fixture_recovery_rejects_evidence_with_mismatched_launch_binding(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    evidence_path = _fixture_evidence_path(tmp_path, launch)
    forged = json.loads(evidence_path.read_text(encoding="utf-8"))
    forged["launch_sha256"] = "f" * 64
    forged["evidence_sha256"] = None
    evidence_path.write_text(
        _canonical_json(TrustedBootstrapEvidence(**forged).to_dict()),
        encoding="utf-8",
    )

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        recover_trusted_bootstrap_fixture(tmp_path, launch=launch)
    assert exc.value.code == "trusted_bootstrap_recovery_evidence_binding_mismatch"


@pytest.mark.parametrize("status", ["passed", "unknown"])
def test_fixture_recovery_rejects_rehashed_target_group_mismatch(tmp_path: Path, status: str):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    evidence_path = _fixture_evidence_path(tmp_path, launch)
    forged = json.loads(evidence_path.read_text(encoding="utf-8"))
    forged["target_pgid"] += 1
    forged["target_group_identity"] = hashlib.sha256(
        _canonical_json({"pid": forged["target_pid"], "pgid": forged["target_pgid"]}).encode("utf-8")
    ).hexdigest()
    forged["status"] = status
    forged["evidence_sha256"] = None
    evidence_path.write_text(
        _canonical_json(TrustedBootstrapEvidence(**forged).to_dict()),
        encoding="utf-8",
    )

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        recover_trusted_bootstrap_fixture(tmp_path, launch=launch)
    assert exc.value.code == "trusted_bootstrap_recovery_target_group_mismatch"


def test_fixture_recovery_rejects_symlinked_terminal_evidence(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    evidence_path = _fixture_evidence_path(tmp_path, launch)
    detached = tmp_path / "detached-evidence.json"
    detached.write_bytes(evidence_path.read_bytes())
    evidence_path.unlink()
    evidence_path.symlink_to(detached)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        recover_trusted_bootstrap_fixture(tmp_path, launch=launch)
    assert exc.value.code == "trusted_bootstrap_recovery_evidence_invalid"


def test_fixture_recovery_rejects_symlinked_journal_directory(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )
    journal = _fixture_evidence_path(tmp_path, launch).parent
    detached = tmp_path / "detached-journal"
    journal.rename(detached)
    journal.symlink_to(detached, target_is_directory=True)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        recover_trusted_bootstrap_fixture(tmp_path, launch=launch)
    assert exc.value.code == "trusted_bootstrap_recovery_registration_invalid"


@pytest.mark.parametrize("ancestor", ["evolution", "producer-batches"])
def test_fixture_recovery_rejects_symlinked_recovery_ancestor(tmp_path: Path, ancestor: str):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )

    original = tmp_path / "evolution" / "producer-batches"
    if ancestor == "evolution":
        original = tmp_path / "evolution"
    detached = tmp_path / f"detached-{ancestor}"
    original.rename(detached)
    original.symlink_to(detached, target_is_directory=True)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        recover_trusted_bootstrap_fixture(tmp_path, launch=launch)
    assert exc.value.code == "trusted_bootstrap_recovery_registration_invalid"


def test_fixture_recovery_rejects_symlinked_workspace_root(tmp_path: Path):
    target = _target(tmp_path)
    launch = _launch(target)
    run_trusted_bootstrap_fixture(
        tmp_path,
        launch=launch,
        descriptor=build_trusted_bootstrap_descriptor(),
        target_executable=target,
    )

    detached = tmp_path.with_name(f"{tmp_path.name}-detached")
    tmp_path.rename(detached)
    tmp_path.symlink_to(detached, target_is_directory=True)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        recover_trusted_bootstrap_fixture(tmp_path, launch=launch)
    assert exc.value.code == "trusted_bootstrap_recovery_workspace_invalid"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 301, True, "1"])
def test_runtime_rejects_invalid_or_unbounded_timeout(tmp_path: Path, timeout: object):
    target = _target(tmp_path)
    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=_launch(target),
            descriptor=build_trusted_bootstrap_descriptor(),
            target_executable=target,
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )
    assert exc.value.code == "trusted_bootstrap_timeout_invalid"


def test_arbitrary_direct_producer_cannot_pose_as_trusted_bootstrap(tmp_path: Path):
    hostile = _target(tmp_path, name="hostile.py")
    hostile_descriptor = build_trusted_bootstrap_descriptor(hostile)
    launch = _launch(hostile, bootstrap=hostile_descriptor)

    with pytest.raises(TrustedBootstrapRuntimeError) as exc:
        run_trusted_bootstrap_fixture(
            tmp_path,
            launch=launch,
            descriptor=hostile_descriptor,
            target_executable=hostile,
        )
    # The runtime only admits its own fixture source as the bootstrap. A direct
    # producer descriptor is rejected before a child can produce trusted evidence.
    assert exc.value.code == "trusted_bootstrap_descriptor_not_allowlisted"
    assert not (tmp_path / "target-marker").exists()


def test_descriptor_mode_cannot_claim_platform_exact_byte_binding(tmp_path: Path):
    descriptor = build_trusted_bootstrap_descriptor()
    with pytest.raises(ValueError):
        build_trusted_bootstrap_descriptor(
            implementation_version=descriptor.implementation_version,
            allowlist_id=descriptor.allowlist_id,
            platform_execution_mode="linux-fd-bound",
        )
