from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import (
    ProducerProcessError,
    build_producer_launch_attestation,
    build_producer_launch_intent,
    producer_process,
    run_producer_process,
)
from lunar_evolution.linux_executable_binding import LinuxExecutableBindingError
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_process import recover_producer_process

DIGEST = "a" * 64


def _fixture(tmp_path: Path, *, mode: str = "success"):
    producer_root = tmp_path / "producer-root"
    producer_root.mkdir()
    script = producer_root / "producer.py"
    descendant_setup = ""
    if mode in {"descendant-pipes", "descendant-redirect", "descendant-stubborn"}:
        child_code = "import time; time.sleep(60)"
        if mode == "descendant-stubborn":
            child_code = (
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "open('../ready', 'w').close(); time.sleep(60)"
            )
        kwargs = ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if mode == "descendant-redirect" else ""
        descendant_setup = f"subprocess.Popen([sys.executable, '-c', {child_code!r}]{kwargs})\n"
        if mode == "descendant-stubborn":
            descendant_setup += "while not pathlib.Path('../ready').exists(): import time; time.sleep(0.01)\n"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, subprocess, sys\n"
        + ("import time\n"
           "while not pathlib.Path('../exit-before-gate').exists(): time.sleep(0.01)\n"
           "sys.exit(7)\n" if mode == "exit-before-gate" else "")
        + "fd = int(os.environ['LUNAR_PRODUCER_GATE_FD'])\n"
        "if os.read(fd, 1) != b'1': sys.exit(4)\n"
        + ("registration = json.loads(pathlib.Path('../process-registration.json').read_text())\n"
           "if registration['pid'] != os.getpid() or registration['pgid'] != os.getpgrp(): sys.exit(5)\n"
           if mode == "gate-order" else "")
        + ("print('x' * 10000)\n" if mode == "overflow" else "")
        + ("sys.exit(3)\n" if mode == "failed" else "")
        + (f"pathlib.Path('../output/producer-result.json').write_text(json.dumps({{'schema_version':'1','producer_id':'fixture','producer_fingerprint':'{DIGEST}','producer_run_id':'run-1','status':'completed','contract_sha256':'{DIGEST}','budget':{{'requests':{3 if mode == 'over-requests' else 1}}},'materials':[]}}))\n" if mode in {"success", "gate-order", "over-requests", "descendant-pipes", "descendant-redirect", "descendant-stubborn"} else "")
        + descendant_setup
        + ("pathlib.Path('../output/actual.json').write_text('external')\n"
           "pathlib.Path('../output/producer-result.json').symlink_to('actual.json')\n"
           if mode == "symlink-envelope" else "")
        + ("import time; time.sleep(2)\n" if mode == "timeout" else ""),
        encoding="utf-8",
    )
    script.chmod(0o755)
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", contract_sha256=DIGEST, evaluator_kind="local",
        evaluator_fingerprint=DIGEST, runner_fingerprint=DIGEST, generator_fingerprint=DIGEST,
        dependency_sha256=DIGEST, environment_sha256=DIGEST, producer_id="fixture", producer_fingerprint=DIGEST,
        executable_relative="producer.py", argv=("producer.py",), working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=2, output_max_bytes=1024 if mode == "overflow" else 65536,
        wall_timeout_seconds=3 if mode in {"descendant-pipes", "descendant-redirect", "descendant-stubborn", "exit-before-gate"} else 1,
    )
    return producer_root, intent, build_producer_launch_attestation(intent, "nonce-001")


def test_attested_process_is_registered_before_gate_and_emits_receipt(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="gate-order")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "completed"
    assert receipt.gate_released is True
    assert receipt.registration_sha256
    assert receipt.envelope_evidence is not None
    batch = tmp_path / "evolution/producer-batches/journal-001"
    registration = json.loads((batch / "process-registration.json").read_text())
    assert registration["registration_sha256"] == receipt.registration_sha256
    assert (registration["pid"], registration["pgid"]) == (receipt.pid, receipt.pgid)
    assert registration["owner_identity"] == receipt.owner_identity
    assert registration["owner_identity_sha256"] == producer_process._sha(receipt.owner_identity)
    assert receipt.owner_identity["pid"] == receipt.pid
    assert (batch / "execution-receipt.json").is_file()


def test_owner_identity_change_denies_cleanup_authority(monkeypatch: pytest.MonkeyPatch):
    owner_identity = {"kind": "test-starttime", "pid": 321, "start": 1}
    process = SimpleNamespace(poll=lambda: 0)
    monkeypatch.setattr(
        producer_process, "_process_owner_identity",
        lambda _pid: {"kind": "test-starttime", "pid": 321, "start": 2},
    )
    assert producer_process._current_process_owned(321, owner_identity, process) is False


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires OS process identity")
def test_os_process_owner_identity_has_subsecond_or_boot_scoped_start():
    observed = producer_process._process_owner_identity(os.getpid())
    assert observed is not None
    assert observed["pid"] == os.getpid()
    if sys.platform == "darwin":
        assert observed["kind"] == "darwin-libproc-starttime-v1"
        assert observed["start_sec"] > 0
        assert 0 <= observed["start_usec"] < 1_000_000
    else:
        assert observed["kind"] == "linux-proc-starttime-v1"
        assert observed["boot_id"]
        assert observed["starttime_ticks"] > 0


def test_missing_identity_requires_live_controller_child_observation(monkeypatch: pytest.MonkeyPatch):
    owner_identity = {"kind": "test-starttime", "pid": 321, "start": 1}
    monkeypatch.setattr(producer_process, "_process_owner_identity", lambda _pid: None)
    assert producer_process._current_process_owned(
        321, owner_identity, SimpleNamespace(poll=lambda: None),
    ) is False
    monkeypatch.setattr(producer_process.os, "getpgid", lambda _pid: 321)
    assert producer_process._current_process_owned(
        321, owner_identity, SimpleNamespace(poll=lambda: 0),
    ) is False

    def missing_pid(_pid: int) -> int:
        raise ProcessLookupError()

    monkeypatch.setattr(producer_process.os, "getpgid", missing_pid)
    assert producer_process._current_process_owned(
        321, owner_identity, SimpleNamespace(poll=lambda: 0),
    ) is True


def test_registration_is_durable_before_gate_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    registration_path = tmp_path / "evolution/producer-batches/journal-001/process-registration.json"
    original_write = os.write
    original_fsync = os.fsync
    gate_observations = []
    synced_inodes = set()

    def checked_fsync(fd):
        opened = os.fstat(fd)
        synced_inodes.add((opened.st_dev, opened.st_ino))
        return original_fsync(fd)

    def checked_write(fd, data):
        if data == b"1":
            registration_info = registration_path.stat()
            assert (registration_info.st_dev, registration_info.st_ino) in synced_inodes
            registration = json.loads(registration_path.read_text())
            gate_observations.append(registration)
        return original_write(fd, data)

    monkeypatch.setattr(producer_process.os, "fsync", checked_fsync)
    monkeypatch.setattr(producer_process.os, "write", checked_write)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert len(gate_observations) == 1
    assert gate_observations[0]["registration_sha256"] == receipt.registration_sha256
    assert gate_observations[0]["pid"] == receipt.pid


def test_launch_environment_does_not_inherit_parent_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    monkeypatch.setenv("LUNAR_SECRET", "parent-only")
    monkeypatch.setenv("PATH", str(tmp_path))
    observed = []

    def checked_popen(*args, **kwargs):
        env = kwargs["env"]
        assert env["PATH"] == os.defpath
        assert env["LANG"] == "C"
        assert "LUNAR_SECRET" not in env
        assert set(env) == {"PATH", "LANG", "LUNAR_PRODUCER_GATE_FD"}
        observed.append(env)
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        popen_factory=checked_popen,
    )
    assert receipt.status == "completed"
    assert len(observed) == 1


def test_attestation_nonce_is_consumed_once(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert exc.value.code == "producer_process_attestation_replayed"


def test_nonce_cannot_be_reused_by_a_different_launch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    second_intent = replace(intent, launch_id="launch-002", journal_id="journal-002", intent_sha256=None)
    second_attestation = build_producer_launch_attestation(second_intent, attestation.nonce)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("replayed nonce must be rejected before spawning a child")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=second_intent, attestation=second_attestation, producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_attestation_replayed"
    assert not (tmp_path / "evolution/producer-batches/journal-002/attestation-consumption.json").exists()
    assert not (tmp_path / "evolution/producer-batches/journal-002/process-registration.json").exists()


@pytest.mark.parametrize("drift", ["bytes", "inode"])
def test_executable_drift_rejected_before_attestation_consumption(tmp_path: Path, drift: str):
    producer_root, intent, attestation = _fixture(tmp_path)
    executable = producer_root / "producer.py"
    if drift == "bytes":
        executable.write_bytes(executable.read_bytes() + b"\n")
    else:
        replacement = producer_root / "replacement.py"
        replacement.write_bytes(executable.read_bytes())
        replacement.chmod(0o755)
        replacement.replace(executable)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("executable drift must be rejected before spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_executable_changed"
    assert not (tmp_path / "evolution/producer-batches/journal-001/attestation-consumption.json").exists()


def test_nonzero_exit_is_failed_without_receipt_projection(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="failed")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_exit_failed"


def test_request_count_over_budget_is_failed(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="over-requests")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_request_limit_exceeded"
    assert receipt.request_count == 3


def test_registration_write_failure_never_releases_work_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    original_write = producer_process._atomic_json

    def fail_registration(path, value, **kwargs):
        if path.name == "process-registration.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_write(path, value, **kwargs)

    monkeypatch.setattr(producer_process, "_atomic_json", fail_registration)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert exc.value.code == "producer_process_receipt_write_unknown"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert not (batch / "output/producer-result.json").exists()
    assert not (batch / "process-registration.json").exists()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_registration_missing"


def test_child_exit_before_gate_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path, mode="exit-before-gate")
    original_write = producer_process._atomic_json
    spawned = []

    def tracked_popen(*args, **kwargs):
        process = producer_process.subprocess.Popen(*args, **kwargs)
        spawned.append(process)
        return process

    def exit_after_registration(path, value, **kwargs):
        original_write(path, value, **kwargs)
        if path.name == "process-registration.json":
            (path.parent / "exit-before-gate").touch()
            assert spawned[0].wait(timeout=2) == 7

    monkeypatch.setattr(producer_process, "_atomic_json", exit_after_registration)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=tracked_popen,
        )
    assert exc.value.code == "producer_process_launch_unknown"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert (batch / "process-registration.json").is_file()
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "output/producer-result.json").exists()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_broken_gate_delivery_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    original_write = producer_process.os.write
    spawned = []

    def tracked_popen(*args, **kwargs):
        process = producer_process.subprocess.Popen(*args, **kwargs)
        spawned.append(process)
        return process

    def fail_gate_write(fd, data):
        if data == b"1":
            raise BrokenPipeError("gate delivery failed")
        return original_write(fd, data)

    monkeypatch.setattr(producer_process.os, "write", fail_gate_write)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=tracked_popen,
        )
    assert exc.value.code == "producer_process_launch_unknown"
    assert spawned[0].wait(timeout=1) != 0
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert (batch / "process-registration.json").is_file()
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "output/producer-result.json").exists()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_terminal_receipt_write_failure_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    original_write = producer_process._atomic_json

    def fail_terminal(path, value, **kwargs):
        if path.name == "execution-receipt.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_write(path, value, **kwargs)

    monkeypatch.setattr(producer_process, "_atomic_json", fail_terminal)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert exc.value.code == "producer_process_receipt_write_unknown"
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_output_limit_is_bounded(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="overflow")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_output_limit_exceeded"
    assert receipt.stdout_evidence.bytes_observed > intent.output_max_bytes


def test_capture_digest_keeps_only_in_budget_prefix_when_one_read_crosses_limit():
    read_fd, write_fd = os.pipe()
    payload = b"a" * 100 + b"b" * 100
    os.write(write_fd, payload)
    os.close(write_fd)
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            process = SimpleNamespace(stdout=stdout, stderr=None, poll=lambda: 0)
            captured, _, overflow, timed_out = producer_process._capture(
                process, limit=100, deadline=time.monotonic() + 1.0,
                monotonic=time.monotonic,
            )
        assert overflow is True
        assert timed_out is False
        assert captured.bytes_observed == 101
        assert captured.truncated is True
        assert captured.sha256 == hashlib.sha256(b"a" * 100).hexdigest()
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable execution snapshots")
def test_darwin_snapshot_survives_source_replacement_after_final_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    producer_root, intent, attestation = _fixture(tmp_path)
    executable = producer_root / "producer.py"
    original = executable.read_bytes()
    observed = {}

    def replacing_popen(*args, **kwargs):
        snapshot = Path(kwargs["executable"])
        flags = os.stat(snapshot, follow_symlinks=False).st_flags
        assert flags & producer_process._UF_IMMUTABLE
        assert snapshot.name == "executable"
        replacement = producer_root / "replacement.py"
        replacement.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib\n"
            "pathlib.Path('../output/producer-result.json').write_text('{}')\n",
            encoding="utf-8",
        )
        replacement.chmod(0o755)
        replacement.replace(executable)
        observed["snapshot"] = snapshot
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path,
        intent=intent,
        attestation=attestation,
        producer_root=producer_root,
        popen_factory=replacing_popen,
    )
    assert receipt.status == "completed"
    assert receipt.execution_binding == "darwin-immutable-snapshot"
    assert receipt.execution_snapshot_sha256 == hashlib.sha256(original).hexdigest()
    assert not observed["snapshot"].exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable execution snapshots")
def test_darwin_snapshot_lock_failure_rejects_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)

    def fail_chflags(*args, **kwargs):
        raise OSError("immutable flags unavailable")

    monkeypatch.setattr(producer_process.os, "chflags", fail_chflags)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("snapshot lock failure must reject before spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path,
            intent=intent,
            attestation=attestation,
            producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_execution_binding_unknown"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux sealed memfd execution")
def test_linux_sealed_executable_survives_source_replacement_after_final_check(tmp_path: Path):
    import fcntl

    producer_root, intent, attestation = _fixture(tmp_path)
    executable = producer_root / "producer.py"
    original_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    observed: dict[str, int] = {}

    def replacing_popen(*args, **kwargs):
        bound_path = kwargs["executable"]
        assert bound_path.startswith("/proc/self/fd/")
        bound_fd = int(bound_path.rsplit("/", 1)[1])
        assert bound_fd in kwargs["pass_fds"]
        required_seals = (
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        )
        assert fcntl.fcntl(bound_fd, fcntl.F_GET_SEALS) & required_seals == required_seals
        observed["fd"] = bound_fd

        replacement = producer_root / "replacement.py"
        replacement.write_text("#!/usr/bin/env python3\nraise SystemExit(9)\n", encoding="utf-8")
        replacement.chmod(0o755)
        replacement.replace(executable)
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        popen_factory=replacing_popen,
    )
    assert receipt.status == "completed"
    assert receipt.execution_binding == "linux-sealed-memfd"
    assert receipt.execution_snapshot_sha256 == original_digest
    assert receipt.execution_snapshot_relative_path is None
    registration = json.loads(
        (tmp_path / "evolution/producer-batches/journal-001/process-registration.json").read_text()
    )
    assert registration["execution_binding"] == "linux-sealed-memfd"
    assert registration["execution_snapshot_sha256"] == original_digest
    with pytest.raises(OSError):
        os.fstat(observed["fd"])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux runner path")
def test_linux_binding_unavailable_rejects_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)

    @contextmanager
    def unavailable(*args, **kwargs):
        raise LinuxExecutableBindingError("linux_execution_binding_unsupported")
        yield

    monkeypatch.setattr(producer_process, "sealed_linux_executable", unavailable)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("an unsupported execution binding must reject before spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_execution_binding_unsupported"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert (batch / "attestation-consumption.json").is_file()
    assert not (batch / "process-registration.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("mode", ["descendant-pipes", "descendant-redirect", "descendant-stubborn"])
def test_leader_exit_cleans_remaining_descendant_group(tmp_path: Path, mode: str):
    producer_root, intent, attestation = _fixture(tmp_path, mode=mode)
    started = time.monotonic()
    receipt = None
    try:
        receipt = run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        )
        assert time.monotonic() - started < intent.wall_timeout_seconds
        assert receipt.status == "completed"
        assert receipt.cleanup_status in {"cleaned", "already_exited"}
        if mode == "descendant-stubborn":
            assert receipt.cleanup_status == "cleaned"
        with pytest.raises(ProcessLookupError):
            os.killpg(receipt.pgid, 0)
    finally:
        if receipt is not None:
            try:
                os.killpg(receipt.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_capture_timeout_does_not_read_open_pipe_after_deadline():
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            process = SimpleNamespace(stdout=stdout, stderr=None, poll=lambda: 0)
            _, _, overflow, timed_out = producer_process._capture(
                process, limit=1024, deadline=0.0, monotonic=lambda: 1.0,
            )
        assert overflow is False
        assert timed_out is True
    finally:
        os.close(write_fd)


def test_remaining_timeout_never_extends_absolute_deadline():
    assert producer_process._remaining_timeout(10.0, lambda: 9.25) == pytest.approx(0.75)
    assert producer_process._remaining_timeout(10.0, lambda: 10.0) == 0.0
    assert producer_process._remaining_timeout(10.0, lambda: 10.25) == 0.0


def test_capture_read_failure_is_unknown(monkeypatch: pytest.MonkeyPatch):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"x")
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            process = SimpleNamespace(stdout=stdout, stderr=None, poll=lambda: None)
            original_read = producer_process.os.read

            def fail_read(fd: int, size: int) -> bytes:
                if fd == read_fd:
                    raise OSError("capture read unavailable")
                return original_read(fd, size)

            monkeypatch.setattr(producer_process.os, "read", fail_read)
            with pytest.raises(ProducerProcessError) as exc:
                producer_process._capture(
                    process, limit=1024, deadline=time.monotonic() + 1.0,
                    monotonic=time.monotonic,
                )
        assert exc.value.code == "producer_process_capture_unknown"
    finally:
        os.close(write_fd)


def test_cleanup_signal_uncertainty_is_persisted_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    producer_root, intent, attestation = _fixture(tmp_path)

    def uncertain_cleanup(registration, **kwargs):
        return ProcessCleanupResult(
            label=registration.label,
            pid=registration.pid,
            pgid=registration.pgid,
            status=ProcessCleanupStatus.KILL_FAILED,
            alive_after=True,
        )

    monkeypatch.setattr(producer_process, "cleanup_registered_process", uncertain_cleanup)
    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
    )
    assert receipt.status == "unknown"
    assert receipt.failure_code == "producer_process_cleanup_unknown"


def test_cleanup_passes_absolute_deadline_and_rechecks_exited_leader(
    monkeypatch: pytest.MonkeyPatch,
):
    registration = producer_process.RegisteredProcess(321, 654, owner_check=lambda: True)
    observed: dict[str, object] = {}

    def checked_cleanup(registration, **kwargs):
        observed.update(kwargs)
        return ProcessCleanupResult(
            label=registration.label,
            pid=registration.pid,
            pgid=registration.pgid,
            status=ProcessCleanupStatus.ALREADY_EXITED,
        )

    monkeypatch.setattr(producer_process, "cleanup_registered_process", checked_cleanup)
    process = SimpleNamespace(returncode=None, poll=lambda: 7)
    producer_process._cleanup(registration, process, deadline=10.0, monotonic=lambda: 9.0)

    assert observed["deadline"] == 10.0
    assert observed["allow_exited_leader_initial"] is True


def test_preparation_time_counts_toward_wall_deadline(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    times = iter((0.0, 2.0))

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("expired launch must not spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            monotonic=lambda: next(times), popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_wall_timeout"
    assert recover_producer_process(tmp_path, journal_id=intent.journal_id)["status"] == "recovery_required"


def test_envelope_read_obeys_wall_deadline(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "producer-result.json").write_text("{}", encoding="utf-8")
    times = iter((0.0, 2.0))
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._read_envelope(
            output / "producer-result.json", relative_path="output/producer-result.json",
            limit=1024, deadline=1.0, monotonic=lambda: next(times),
        )
    assert exc.value.code == "producer_process_wall_timeout"


def test_envelope_rejects_duplicate_json_keys(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "producer-result.json").write_text('{"budget":{"requests":1,"requests":1}}', encoding="utf-8")
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._read_envelope(
            output / "producer-result.json", relative_path="output/producer-result.json",
            limit=1024, deadline=1.0, monotonic=lambda: 0.0,
        )
    assert exc.value.code == "producer_process_envelope_invalid"


def test_timeout_is_terminal_without_relaunch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="timeout")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status in {"failed", "unknown"}
    assert receipt.failure_code in {"producer_process_wall_timeout", "producer_process_cleanup_unknown"}


def test_symlink_envelope_is_rejected_with_terminal_receipt(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="symlink-envelope")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_envelope_invalid"
    assert receipt.envelope_evidence is None
    assert (tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json").is_file()


def test_replaced_envelope_during_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    output = tmp_path / "evolution/producer-batches/journal-001/output"
    output.mkdir(parents=True)
    envelope = output / "producer-result.json"
    replacement = output / "replacement.json"
    replacement.write_text("replacement", encoding="utf-8")
    original_open = os.open
    replaced = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == envelope.name and kwargs.get("dir_fd") is not None and not replaced:
            replacement.replace(envelope)
            replaced = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(producer_process.os, "open", swapping_open)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert replaced
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_envelope_changed"
    assert receipt.envelope_evidence is None


def test_replaced_output_directory_during_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    batch = tmp_path / "evolution/producer-batches/journal-001"
    output = batch / "output"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "producer-result.json").write_text("{}", encoding="utf-8")
    original_open = os.open
    replaced = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == "producer-result.json" and kwargs.get("dir_fd") is not None and not replaced:
            output.replace(batch / "moved-output")
            output.symlink_to(outside, target_is_directory=True)
            replaced = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(producer_process.os, "open", swapping_open)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert replaced
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_directory_invalid"
    assert receipt.envelope_evidence is None


def test_recovery_reads_terminal_receipt_without_relaunch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("recovery must not relaunch the producer")

    monkeypatch.setattr(producer_process.subprocess, "Popen", forbidden_spawn)
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["receipt_sha256"] == receipt.receipt_sha256
    assert recovered["registration_sha256"] == receipt.registration_sha256


def test_missing_terminal_receipt_requires_recovery_without_relaunch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    (tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json").unlink()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_recovery_rejects_registration_owner_identity_mismatch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    batch = tmp_path / "evolution/producer-batches/journal-001"
    (batch / "execution-receipt.json").unlink()
    path = batch / "process-registration.json"
    registration = json.loads(path.read_text())
    registration["owner_identity"]["pid"] += 1
    registration["owner_identity_sha256"] = producer_process._sha(registration["owner_identity"])
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    path.write_bytes(producer_process._canonical(registration))
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_registration_invalid"


def test_recovery_rejects_symlinked_receipt(tmp_path: Path):
    batch = tmp_path / "evolution/producer-batches/journal-001"
    batch.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (batch / "execution-receipt.json").symlink_to(outside)
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id="journal-001")
    assert exc.value.code == "producer_process_recovery_receipt_invalid"


def test_recovery_rejects_tampered_receipt_digest(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    path = tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json"
    altered = json.loads(path.read_text())
    altered["run_id"] = "different-run"
    path.write_text(json.dumps(altered), encoding="utf-8")

    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_receipt_invalid"


def test_recovery_rejects_duplicate_receipt_keys(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    path = tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json"
    path.write_text(path.read_text()[:-1] + ',"status":"completed"}', encoding="utf-8")
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_receipt_invalid"


def test_recovery_rejects_symlinked_batch_directory(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    batches = tmp_path / "evolution/producer-batches"
    actual = batches / "journal-001"
    moved = batches / "moved"
    actual.replace(moved)
    actual.symlink_to(moved, target_is_directory=True)

    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_receipt_invalid"
