from __future__ import annotations

import json
import os
import signal
import time
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
        "fd = int(os.environ['LUNAR_PRODUCER_GATE_FD'])\n"
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
        wall_timeout_seconds=3 if mode in {"descendant-pipes", "descendant-redirect", "descendant-stubborn"} else 1,
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
    assert (batch / "execution-receipt.json").is_file()


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
