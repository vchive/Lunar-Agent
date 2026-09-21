"""Deterministic replacement tests for read-only comparison evidence validation."""

import hashlib
import os
from pathlib import Path

import pytest

from lunar_evolution import benchmark_result as module
from lunar_evolution.benchmark_result import (
    BenchmarkComparisonResult,
    BenchmarkResultError,
    ComparisonArmResult,
    bind_benchmark_comparison_result_evidence,
    parse_benchmark_comparison_result,
)
from tests.test_benchmark_result import _plan, _result


def _evidence(tmp_path):
    root = tmp_path / "evidence"
    (root / "nested").mkdir(parents=True)
    content = b"local evidence\n"
    source = root / "nested" / "receipt.bin"
    source.write_bytes(content)
    plan = _plan()
    arms = tuple(
        ComparisonArmResult(
            arm.id, "completed", 10, 2, 1, 0.5,
            hashlib.sha256(content).hexdigest(), "nested/receipt.bin", len(content),
        ) for arm in plan.arms
    )
    result = BenchmarkComparisonResult(
        plan.comparison_id, module._result_id(plan.comparison_id, arms), arms,
    )
    return root, source, plan, result


@pytest.mark.parametrize("component", ["file", "directory"])
def test_substitution_between_check_and_open_is_rejected(tmp_path, monkeypatch, component):
    root, source, plan, result = _evidence(tmp_path)
    target = source if component == "file" else source.parent
    outside = tmp_path / "outside"
    if component == "file":
        outside.write_bytes(source.read_bytes())
    else:
        outside.mkdir()
        (outside / source.name).write_bytes(source.read_bytes())
    saved = target.with_name("retained")
    original_open, original_path_open = os.open, Path.open
    substituted = False

    def replace_during_open(callback):
        nonlocal substituted
        substituted = True
        target.rename(saved)
        target.symlink_to(outside)
        try:
            return callback()
        finally:
            target.unlink()
            saved.rename(target)

    def fd_open(name, flags, *args, **kwargs):
        if not substituted and str(name) == target.name:
            return replace_during_open(lambda: original_open(name, flags, *args, **kwargs))
        return original_open(name, flags, *args, **kwargs)

    def path_open(path, *args, **kwargs):
        if not substituted and path == source:
            return replace_during_open(lambda: original_path_open(path, *args, **kwargs))
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", fd_open)
    monkeypatch.setattr(Path, "open", path_open)
    with pytest.raises(BenchmarkResultError):
        bind_benchmark_comparison_result_evidence(result, plan, root)
    assert substituted


def test_result_json_rejects_oversize_before_read(tmp_path, monkeypatch):
    source = tmp_path / "result.json"
    with source.open("wb") as stream:
        stream.truncate(module.MAX_RESULT_BYTES + 1)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("unbounded read_bytes"))
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("oversize data was read"))
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_too_large$"):
        parse_benchmark_comparison_result(source)


def test_result_json_regular_file_roundtrip(tmp_path):
    import json

    result = _result(_plan())
    source = tmp_path / "result.json"
    source.write_text(json.dumps(result.to_dict()))
    assert parse_benchmark_comparison_result(source).digest() == result.digest()


@pytest.mark.parametrize("kind", ["directory", "fifo", "symlink", "missing"])
def test_result_json_rejects_non_regular_files(tmp_path, kind):
    source = tmp_path / "result.json"
    if kind == "directory":
        source.mkdir()
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"{}")
        source.symlink_to(outside)
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_invalid$"):
        parse_benchmark_comparison_result(source)


@pytest.mark.parametrize("change", ["replace", "rewrite", "grow", "delete", "directory", "root"])
def test_file_or_directory_change_during_read_is_rejected(tmp_path, monkeypatch, change):
    root, source, plan, result = _evidence(tmp_path)
    content = source.read_bytes()
    before = source.stat()
    original_read = os.read
    changed = False

    def read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            if change == "replace":
                replacement = source.with_name("replacement")
                replacement.write_bytes(content)
                replacement.replace(source)
            elif change == "rewrite":
                source.write_bytes(b"x" * len(content))
                os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
            elif change == "grow":
                with source.open("ab") as stream:
                    stream.write(b"x")
            elif change == "delete":
                source.unlink()
            else:
                target = root if change == "root" else source.parent
                target.rename(target.with_name("retained"))
                target.mkdir()
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_evidence_changed$"):
        bind_benchmark_comparison_result_evidence(result, plan, root)
    assert changed


@pytest.mark.parametrize("kind", ["root_link", "ancestor_link", "file_link", "fifo", "directory"])
def test_evidence_rejects_bad_nodes_without_reading(tmp_path, monkeypatch, kind):
    root, source, plan, result = _evidence(tmp_path)
    if kind in {"root_link", "ancestor_link"}:
        target = root if kind == "root_link" else source.parent
        target.rename(target.with_name("retained"))
        target.symlink_to(target.with_name("retained"))
    else:
        source.unlink()
        if kind == "directory":
            source.mkdir()
        elif kind == "fifo":
            os.mkfifo(source)
        else:
            source.symlink_to(tmp_path / "absent")
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("invalid node was read"))
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_evidence_unsafe$"):
        bind_benchmark_comparison_result_evidence(result, plan, root)


@pytest.mark.parametrize("valid", [True, False])
def test_opened_descriptors_are_closed(tmp_path, monkeypatch, valid):
    root, source, plan, result = _evidence(tmp_path)
    if not valid:
        source.write_bytes(b"wrong size")
    opened = []
    original_open = os.open

    def track_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", track_open)
    if valid:
        assert bind_benchmark_comparison_result_evidence(result, plan, root) == result
    else:
        with pytest.raises(BenchmarkResultError):
            bind_benchmark_comparison_result_evidence(result, plan, root)
    assert opened
    for descriptor in set(opened):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_large_json_is_read_in_bounded_chunks(tmp_path, monkeypatch):
    source = tmp_path / "result.json"
    source.write_bytes(b" " * module.MAX_RESULT_BYTES)
    original_read = os.read
    read_sizes = []

    def read(descriptor, size):
        read_sizes.append(size)
        return original_read(descriptor, size)

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_invalid$"):
        parse_benchmark_comparison_result(source)
    assert read_sizes
    assert max(read_sizes) <= 64 * 1024
    assert sum(read_sizes) <= module.MAX_RESULT_BYTES + 1


def test_result_file_through_ancestor_symlink_is_rejected(tmp_path):
    source = tmp_path / "result.json"
    source.write_bytes(b"{}")
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path)
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_invalid$"):
        parse_benchmark_comparison_result(linked / source.name)


def test_binding_reads_do_not_change_source_content_or_create_outputs(tmp_path):
    root, source, plan, result = _evidence(tmp_path)
    content = source.read_bytes()
    before = source.stat()
    names = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    assert bind_benchmark_comparison_result_evidence(result, plan, root) == result
    assert source.read_bytes() == content
    after = source.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*")) == names


@pytest.mark.parametrize("source", [None, 42, "bad\x00path", "bad\ud800path"])
def test_invalid_result_file_path_has_fixed_error(source):
    with pytest.raises(BenchmarkResultError, match="^benchmark_result_invalid$"):
        parse_benchmark_comparison_result(source)
