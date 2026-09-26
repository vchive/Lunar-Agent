from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

from lunar_evolution import producer_process
from lunar_evolution.producer_bootstrap import (
    TrustedBootstrapDescriptor,
    build_trusted_bootstrap_launch,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.trusted_bootstrap_binding import (
    TrustedBootstrapBindingError,
    prepare_trusted_executable_pair,
)

DIGEST = "a" * 64


def _fixture(tmp_path: Path, *, bootstrap_mode: int = 0o755):
    bootstrap = tmp_path / "bootstrap"
    bootstrap.write_bytes(b"#!/bin/sh\nexit 0\n")
    bootstrap.chmod(bootstrap_mode)
    root = tmp_path / "producer-root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"#!/bin/sh\nexit 3\n")
    target.chmod(0o755)
    batch = tmp_path / "batch"
    batch.mkdir()
    info = bootstrap.stat()
    descriptor = TrustedBootstrapDescriptor(
        implementation_version="test-bootstrap-1",
        bootstrap_sha256=hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
        size=info.st_size, device=info.st_dev, inode=info.st_ino,
        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
        allowlist_id="local-test",
        platform_execution_mode="darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-fd-bound",
    )
    intent = build_producer_launch_intent(
        producer_root=root, launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", contract_sha256=DIGEST,
        evaluator_kind="local", evaluator_fingerprint=DIGEST, runner_fingerprint=DIGEST,
        generator_fingerprint=DIGEST, dependency_sha256=DIGEST, environment_sha256=DIGEST,
        producer_id="fixture", producer_fingerprint=DIGEST, executable_relative="target",
        argv=("target",), working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024, wall_timeout_seconds=5,
    )
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    launch = build_trusted_bootstrap_launch(intent, attestation, descriptor)
    return bootstrap, target, root, batch, descriptor, launch, intent, attestation


def _prepare(values, *, deadline=None, monotonic=time.monotonic):
    bootstrap, _, root, batch, descriptor, launch, intent, attestation = values
    return prepare_trusted_executable_pair(
        bootstrap_source=bootstrap, producer_root=root, batch=batch,
        descriptor=descriptor, launch=launch, intent=intent, attestation=attestation,
        deadline=time.monotonic() + 5 if deadline is None else deadline,
        monotonic=monotonic,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_pair_has_distinct_immutable_bytes_after_sources_change(tmp_path: Path):
    values = _fixture(tmp_path)
    bootstrap, target, _, batch, *_ = values
    original_bootstrap = bootstrap.read_bytes()
    original_target = target.read_bytes()
    pair = None
    try:
        with _prepare(values) as pair:
            assert pair.pass_fds == ()
            assert pair.bootstrap.snapshot.relative_path == ".producer-snapshots/bootstrap"
            assert pair.target.snapshot.relative_path == ".producer-snapshots/target"
            bootstrap.write_bytes(b"#!/bin/sh\nexit 9\n")
            target.write_bytes(b"#!/bin/sh\nexit 8\n")
            assert Path(pair.bootstrap.executable).read_bytes() == original_bootstrap
            assert Path(pair.target.executable).read_bytes() == original_target
            for bound in (pair.bootstrap, pair.target):
                assert os.stat(bound.executable, follow_symlinks=False).st_flags & producer_process._UF_IMMUTABLE
        assert Path(pair.bootstrap.executable).exists()
        assert Path(pair.target.executable).exists()
    finally:
        if pair is not None:
            producer_process._remove_executable_snapshot(pair.bootstrap.snapshot, batch)
            producer_process._remove_executable_snapshot(pair.target.snapshot, batch)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_second_binding_failure_cleans_first_before_spawn(tmp_path: Path, monkeypatch):
    from lunar_evolution import trusted_bootstrap_binding as binding

    values = _fixture(tmp_path)
    batch = values[3]
    real_snapshot = binding._snapshot_executable

    def fail_target(*args, role, **kwargs):
        if role == "target":
            raise producer_process.ProducerProcessError("producer_process_execution_binding_unknown")
        return real_snapshot(*args, role=role, **kwargs)

    monkeypatch.setattr(binding, "_snapshot_executable", fail_target)
    with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(values):
        pytest.fail("second binding failure must not yield a pair")
    assert exc.value.code == "producer_process_execution_binding_unknown"
    assert not (batch / ".producer-snapshots/bootstrap").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_rejects_existing_role_snapshot_without_replacing_it(tmp_path: Path):
    values = _fixture(tmp_path)
    batch = values[3]
    snapshot_dir = batch / ".producer-snapshots"
    snapshot_dir.mkdir()
    existing = snapshot_dir / "target"
    existing.write_bytes(b"previous attempt")

    with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(values):
        pytest.fail("existing role snapshot must not yield a pair")
    assert exc.value.code == "trusted_binding_snapshot_exists"
    assert existing.read_bytes() == b"previous attempt"
    assert not (snapshot_dir / "bootstrap").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_cleanup_failure_is_reported_and_other_snapshot_is_removed(tmp_path: Path, monkeypatch):
    from lunar_evolution import trusted_bootstrap_binding as binding

    values = _fixture(tmp_path, bootstrap_mode=0o644)
    batch = values[3]
    real_remove = binding._remove_executable_snapshot

    def fail_target_cleanup(snapshot, batch_path):
        if snapshot.relative_path != ".producer-snapshots/target":
            real_remove(snapshot, batch_path)

    monkeypatch.setattr(binding, "_remove_executable_snapshot", fail_target_cleanup)
    try:
        with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(values):
            pytest.fail("uncertain cleanup must not yield a pair")
        assert exc.value.code == "trusted_binding_cleanup_unknown"
        assert not (batch / ".producer-snapshots/bootstrap").exists()
        assert (batch / ".producer-snapshots/target").exists()
    finally:
        real_remove(producer_process.ProducerExecutableSnapshot(
            ".producer-snapshots/target", "", 0, "darwin-immutable-snapshot",
        ), batch)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_partial_publication_is_retained_and_reported(tmp_path: Path, monkeypatch):
    from lunar_evolution import trusted_bootstrap_binding as binding

    values = _fixture(tmp_path)
    batch = values[3]
    real_snapshot = binding._snapshot_executable
    target_snapshot = None

    def fail_after_target_publish(*args, role, **kwargs):
        nonlocal target_snapshot
        snapshot = real_snapshot(*args, role=role, **kwargs)
        if role == "target":
            target_snapshot = snapshot
            raise producer_process.ProducerProcessError("producer_process_execution_binding_unknown")
        return snapshot

    monkeypatch.setattr(binding, "_snapshot_executable", fail_after_target_publish)
    try:
        with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(values):
            pytest.fail("partial publication must not yield a pair")
        assert exc.value.code == "trusted_binding_cleanup_unknown"
        assert not (batch / ".producer-snapshots/bootstrap").exists()
        assert (batch / ".producer-snapshots/target").exists()
    finally:
        producer_process._remove_executable_snapshot(target_snapshot, batch)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_deadline_between_bindings_cleans_first(tmp_path: Path, monkeypatch):
    from lunar_evolution import trusted_bootstrap_binding as binding

    values = _fixture(tmp_path)
    batch = values[3]
    now = [0.0]
    real_snapshot = binding._snapshot_executable

    def advance_after_bootstrap(*args, role, **kwargs):
        snapshot = real_snapshot(*args, role=role, **kwargs)
        if role == "bootstrap":
            now[0] = 11.0
        return snapshot

    monkeypatch.setattr(binding, "_snapshot_executable", advance_after_bootstrap)
    with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(
        values, deadline=10.0, monotonic=lambda: now[0],
    ):
        pytest.fail("expired deadline must not yield a pair")
    assert exc.value.code == "producer_process_wall_timeout"
    assert not (batch / ".producer-snapshots/bootstrap").exists()


def test_pair_rejects_source_drift_before_binding(tmp_path: Path):
    values = _fixture(tmp_path)
    values[1].write_bytes(b"#!/bin/sh\nexit 4\n")
    with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(values):
        pytest.fail("changed target must not be bound")
    assert exc.value.code == "trusted_binding_source_changed"


def test_pair_rejects_permissive_launch_equality(tmp_path: Path):
    values = _fixture(tmp_path)

    class EqualToEverything:
        def __eq__(self, other):
            return True

    bootstrap, _, root, batch, descriptor, _, intent, attestation = values
    with pytest.raises(TrustedBootstrapBindingError) as exc, prepare_trusted_executable_pair(
        bootstrap_source=bootstrap, producer_root=root, batch=batch, descriptor=descriptor,
        launch=EqualToEverything(), intent=intent, attestation=attestation,
        deadline=time.monotonic() + 5,
    ):
        pytest.fail("untyped launch must not yield a pair")
    assert exc.value.code == "trusted_binding_launch_mismatch"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable snapshots")
def test_darwin_pair_rejects_nonexecutable_bootstrap_and_cleans_snapshots(tmp_path: Path):
    values = _fixture(tmp_path, bootstrap_mode=0o644)
    batch = values[3]
    with pytest.raises(TrustedBootstrapBindingError) as exc, _prepare(values):
        pytest.fail("nonexecutable bootstrap must not yield a pair")
    assert exc.value.code == "trusted_binding_mode_invalid"
    assert not (batch / ".producer-snapshots/bootstrap").exists()
    assert not (batch / ".producer-snapshots/target").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux sealed memfd")
def test_linux_pair_keeps_both_sealed_descriptors_until_context_exit(tmp_path: Path):
    import fcntl

    values = _fixture(tmp_path)
    bootstrap, target = values[:2]
    original = (bootstrap.read_bytes(), target.read_bytes())
    with _prepare(values) as pair:
        assert len(pair.pass_fds) == 2
        assert pair.bootstrap.executable == f"/proc/self/fd/{pair.bootstrap.pass_fd}"
        assert pair.target.executable == f"/proc/self/fd/{pair.target.pass_fd}"
        bootstrap.write_bytes(b"#!/bin/sh\nexit 9\n")
        target.write_bytes(b"#!/bin/sh\nexit 8\n")
        for bound, expected in zip((pair.bootstrap, pair.target), original, strict=True):
            assert Path(bound.executable).read_bytes() == expected
            assert fcntl.fcntl(bound.pass_fd, fcntl.F_GET_SEALS) & fcntl.F_SEAL_WRITE
    for fd in pair.pass_fds:
        with pytest.raises(OSError):
            os.fstat(fd)
