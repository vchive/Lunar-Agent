"""The whole static validation pipeline reads only bounded, unchanged local files."""

import os
from pathlib import Path

import pytest

from lunar_evolution.benchmark_comparison import (
    BenchmarkComparisonError,
    parse_benchmark_comparison_plan,
)
from lunar_evolution.benchmark_task import (
    BenchmarkTaskEnvelope,
    BenchmarkTaskError,
    admit_benchmark_task_envelope,
    parse_benchmark_task_envelope,
)
from tests.test_benchmark_task import _payload


@pytest.mark.parametrize(("parser", "error", "limit"), [
    (parse_benchmark_task_envelope, BenchmarkTaskError, 128 * 1024),
    (parse_benchmark_comparison_plan, BenchmarkComparisonError, 256 * 1024),
])
def test_metadata_oversize_rejected_before_read(tmp_path, monkeypatch, parser, error, limit):
    source = tmp_path / "document.json"
    with source.open("wb") as stream:
        stream.truncate(limit + 1)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("unbounded read_bytes"))
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("oversize content read"))
    with pytest.raises(error, match="too_large"):
        parser(source)


def _admit(root):
    return admit_benchmark_task_envelope(
        BenchmarkTaskEnvelope.from_dict(_payload()), contract_sha256="c" * 64,
        input_root=root, model_profile_sha256="d" * 64, evaluator_fingerprint="b" * 64,
    )


def test_input_substitution_at_open_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "task.json"
    content = b'{"items":[1]}'
    source.write_bytes(content)
    outside = tmp_path / "other.json"
    outside.write_bytes(content)
    saved = tmp_path / "saved.json"
    original_open, original_path_open = os.open, Path.open
    substituted = False

    def during_open(callback):
        nonlocal substituted
        substituted = True
        source.rename(saved)
        source.symlink_to(outside)
        try:
            return callback()
        finally:
            source.unlink()
            saved.rename(source)

    def fd_open(name, flags, *args, **kwargs):
        if not substituted and str(name) == source.name:
            return during_open(lambda: original_open(name, flags, *args, **kwargs))
        return original_open(name, flags, *args, **kwargs)

    def path_open(path, *args, **kwargs):
        if not substituted and path == source:
            return during_open(lambda: original_path_open(path, *args, **kwargs))
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", fd_open)
    monkeypatch.setattr(Path, "open", path_open)
    with pytest.raises(BenchmarkTaskError):
        _admit(tmp_path)
    assert substituted


@pytest.mark.parametrize("parser", [parse_benchmark_task_envelope, parse_benchmark_comparison_plan])
def test_metadata_ancestor_link_is_rejected(tmp_path, parser):
    source = tmp_path / "document.json"
    source.write_bytes(b"{}")
    linked = tmp_path / "link"
    linked.symlink_to(tmp_path)
    with pytest.raises((BenchmarkTaskError, BenchmarkComparisonError)):
        parser(linked / source.name)


def test_input_same_size_change_during_read_rejected(tmp_path, monkeypatch):
    source = tmp_path / "task.json"
    source.write_bytes(b'{"items":[1]}')
    original_read = os.read
    changed = False

    def read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            source.write_bytes(b'{"items":[2]}')
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(BenchmarkTaskError, match="input_changed"):
        _admit(tmp_path)
    assert changed


@pytest.mark.parametrize("mutation", ["path", "absolute_path", "size", "schema", "task"])
def test_task_admission_replays_dto_before_opening_files(monkeypatch, mutation):
    envelope = BenchmarkTaskEnvelope.from_dict(_payload())
    if mutation == "path":
        object.__setattr__(envelope.inputs[0], "path", "../outside.json")
    elif mutation == "absolute_path":
        object.__setattr__(envelope.inputs[0], "path", "/outside.json")
    elif mutation == "size":
        object.__setattr__(envelope.inputs[0], "size", 16 * 1024 * 1024 + 1)
    elif mutation == "schema":
        object.__setattr__(envelope, "schema_version", "changed")
    else:
        object.__setattr__(envelope, "task", None)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("invalid DTO opened files"))
    with pytest.raises(BenchmarkTaskError, match="^benchmark_task_envelope_invalid$"):
        admit_benchmark_task_envelope(
            envelope, contract_sha256="c" * 64, input_root="unused",
            model_profile_sha256="d" * 64, evaluator_fingerprint="b" * 64,
        )
