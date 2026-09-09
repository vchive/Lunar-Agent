import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from famou.tools import LocalToolRegistry


@pytest.mark.parametrize("failure", ["fsync", "replace"])
@pytest.mark.parametrize("incumbent", [False, True])
def test_failed_publication_preserves_incumbent_and_reports_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, incumbent: bool,
) -> None:
    destination = tmp_path / "candidate.json"
    original = b'{"candidate": "previous complete result"}'
    if incumbent:
        destination.write_bytes(original)

    def fail(*args, **kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, failure, fail)
    result = LocalToolRegistry().execute(
        "write_file", {"path": destination.name, "content": "new complete result"}, tmp_path,
    )

    assert not result.success
    assert not result.artifacts
    assert "injected publication failure" in result.output
    if incumbent:
        assert destination.read_bytes() == original
    else:
        assert not destination.exists()
    assert set(tmp_path.iterdir()) == ({destination} if incumbent else set())


@pytest.mark.parametrize("interruption", [OSError, KeyboardInterrupt])
def test_interrupted_partial_write_preserves_complete_incumbent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: type[BaseException],
) -> None:
    destination = tmp_path / "candidate.json"
    destination.write_bytes(b"complete incumbent")
    original_temporary = tempfile.NamedTemporaryFile

    @contextmanager
    def interrupted_temporary(*args, **kwargs):
        with original_temporary(*args, **kwargs) as stream:
            class InterruptedWriter:
                name = stream.name

                def write(self, content):
                    stream.write(content[:5])
                    stream.flush()
                    raise interruption("interrupted partial write")

            yield InterruptedWriter()

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", interrupted_temporary)
    registry = LocalToolRegistry()
    arguments = {"path": destination.name, "content": "complete replacement"}
    if interruption is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt, match="interrupted partial write"):
            registry.execute("write_file", arguments, tmp_path)
    else:
        result = registry.execute("write_file", arguments, tmp_path)
        assert not result.success
        assert not result.artifacts
        assert "interrupted partial write" in result.output
    assert destination.read_bytes() == b"complete incumbent"
    assert set(tmp_path.iterdir()) == {destination}


def test_publication_uses_complete_unique_same_directory_files_and_preserves_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "output" / "solve.py"
    destination.parent.mkdir()
    destination.write_text("old candidate", encoding="utf-8")
    destination.chmod(0o751)
    registry = LocalToolRegistry()
    replacement_paths = []
    synchronized_paths = []
    original_replace = os.replace
    original_fsync = os.fsync
    expected_old = b"old candidate"
    expected_new = b""

    def observe_fsync(descriptor):
        original_fsync(descriptor)
        pending = set(destination.parent.iterdir()) - {destination}
        assert len(pending) == 1
        temporary = pending.pop()
        assert temporary.read_bytes() == expected_new
        synchronized_paths.append(temporary)

    def observe_replace(source, target):
        temporary = Path(source)
        assert temporary.parent == destination.parent
        assert Path(target) == destination
        assert temporary != destination
        assert destination.read_bytes() == expected_old
        assert temporary.read_bytes() == expected_new
        assert synchronized_paths[-1] == temporary
        replacement_paths.append(temporary)
        original_replace(source, target)

    monkeypatch.setattr(os, "fsync", observe_fsync)
    monkeypatch.setattr(os, "replace", observe_replace)
    for content in ("#!/usr/bin/env python3\nprint('初始候选')\n", "print('改进候选')\n"):
        expected_new = content.encode("utf-8")
        result = registry.execute(
            "write_file", {"path": "output/solve.py", "content": content}, tmp_path,
        )
        assert result.success
        assert result.artifacts == ("output/solve.py",)
        assert destination.read_bytes() == expected_new
        assert stat.S_IMODE(destination.stat().st_mode) == 0o751
        assert set(destination.parent.iterdir()) == {destination}
        expected_old = expected_new

    assert len(replacement_paths) == 2
    assert len(set(replacement_paths)) == 2


def test_write_bound_counts_utf8_bytes_and_does_not_mutate_on_rejection(tmp_path: Path) -> None:
    registry = LocalToolRegistry()
    candidate = tmp_path / "candidate.txt"
    accepted = registry.execute(
        "write_file", {"path": candidate.name, "content": "é" * 500_000}, tmp_path,
    )
    assert accepted.success
    assert candidate.stat().st_size == 1_000_000
    previous = candidate.read_bytes()

    rejected = registry.execute(
        "write_file", {"path": candidate.name, "content": "é" * 500_001}, tmp_path,
    )
    assert not rejected.success
    assert not rejected.artifacts
    assert candidate.read_bytes() == previous
    assert set(tmp_path.iterdir()) == {candidate}


@pytest.mark.parametrize("escape", ["relative", "symlink"])
def test_atomic_write_keeps_workspace_confinement(tmp_path: Path, escape: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside original", encoding="utf-8")
    path = "../outside.txt"
    if escape == "symlink":
        (workspace / "link.txt").symlink_to(outside)
        path = "link.txt"
    result = LocalToolRegistry().execute(
        "write_file", {"path": path, "content": "replacement"}, workspace,
    )
    assert not result.success
    assert not result.artifacts
    assert outside.read_text(encoding="utf-8") == "outside original"
    assert sorted(item.name for item in workspace.iterdir()) == (
        ["link.txt"] if escape == "symlink" else []
    )
