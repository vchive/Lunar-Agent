"""Filesystem safety and failure boundaries for candidate workspace materialization."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from famou.candidate_bundle import parse_candidate_source_bundle
from famou.candidate_workspace import CandidateWorkspaceError, materialize_candidate_source_bundle

CONTRACT = "a" * 64


def _fixture(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    files = {"main.py": b"print('candidate')\n", "lib/helper.py": b"VALUE = 42\n"}
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    bundle = parse_candidate_source_bundle({
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT, "entrypoint": "main.py",
        "files": [
            {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in files.items()
        ],
    })
    parent = tmp_path / "workspaces"
    parent.mkdir()
    return source, bundle, parent


def _materialize(source, bundle, parent, **kwargs):
    return materialize_candidate_source_bundle(
        bundle, source_root=source, workspace_root=parent,
        contract_sha256=CONTRACT, **kwargs,
    )


def test_materialization_uses_private_modes_and_only_declared_files(tmp_path):
    source, bundle, parent = _fixture(tmp_path)
    (source / "unlisted.txt").write_bytes(b"ignored")
    result = _materialize(source, bundle, parent)
    assert result.workspace_path.parent == parent
    assert result.workspace_path.stat().st_mode & 0o777 == 0o700
    assert (result.workspace_path / "main.py").stat().st_mode & 0o777 == 0o600
    assert (result.workspace_path / "lib").stat().st_mode & 0o777 == 0o700
    assert not (result.workspace_path / "unlisted.txt").exists()
    assert (result.workspace_path / result.entrypoint).is_file()


@pytest.mark.parametrize("kind", ["root_link", "ancestor_link", "file_link", "fifo", "directory"])
def test_source_nodes_are_rejected_and_no_workspace_is_left(tmp_path, kind):
    source, bundle, parent = _fixture(tmp_path)
    target = source / "main.py"
    if kind == "root_link":
        retained = source.with_name("retained-source")
        source.rename(retained)
        source.symlink_to(retained)
    elif kind == "ancestor_link":
        directory = source / "lib"
        retained = directory.with_name("retained-lib")
        directory.rename(retained)
        directory.symlink_to(retained)
    else:
        target.unlink()
        if kind == "file_link":
            target.symlink_to(tmp_path / "outside.py")
        elif kind == "fifo":
            os.mkfifo(target)
        else:
            target.mkdir()
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_source_"):
        _materialize(source, bundle, parent)
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("root_kind", ["missing", "file", "link", "fifo"])
def test_workspace_parent_must_be_existing_physical_directory(tmp_path, root_kind):
    source, bundle, _ = _fixture(tmp_path)
    parent = tmp_path / "workspace-parent"
    if root_kind == "file":
        parent.write_bytes(b"file")
    elif root_kind == "link":
        parent.symlink_to(tmp_path)
    elif root_kind == "fifo":
        os.mkfifo(parent)
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_workspace_root_unsafe$"):
        _materialize(source, bundle, parent)


def test_source_and_workspace_parent_must_be_disjoint(tmp_path):
    source, bundle, _ = _fixture(tmp_path)
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_workspace_root_unsafe$"):
        _materialize(source, bundle, source)
    child = source / "workspaces"
    child.mkdir()
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_workspace_root_unsafe$"):
        _materialize(source, bundle, child)


def test_source_changes_between_observations_are_rejected_and_cleaned(tmp_path, monkeypatch):
    source, bundle, parent = _fixture(tmp_path)
    original_read = os.read
    changed = False

    def read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            path = source / "lib/helper.py"
            path.write_bytes(b"VALUE = 43\n")
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_source_changed$"):
        _materialize(source, bundle, parent)
    assert changed
    assert list(parent.iterdir()) == []


def test_destination_write_failure_is_fixed_and_best_effort_cleaned(tmp_path, monkeypatch):
    source, bundle, parent = _fixture(tmp_path)
    original_write = os.write
    writes = 0

    def write(descriptor, data):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OSError("injected write failure")
        return original_write(descriptor, data)

    monkeypatch.setattr(os, "write", write)
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_destination_write_failed$"):
        _materialize(source, bundle, parent)
    assert writes == 1
    assert list(parent.iterdir()) == []


def test_destination_parent_replacement_does_not_escape_workspace_root(tmp_path, monkeypatch):
    source, bundle, parent = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = os.open
    replaced = False

    def open_file(path, flags, *args, **kwargs):
        nonlocal replaced
        workspaces = list(parent.iterdir())
        if not replaced and Path(path).name in {"lib", "helper.py"} and len(workspaces) == 1:
            target = workspaces[0] / "lib"
            if target.is_dir():
                replaced = True
                target.rename(target.with_name("retained-lib"))
                target.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_file)
    with pytest.raises(CandidateWorkspaceError):
        _materialize(source, bundle, parent)
    assert replaced
    assert not list(outside.iterdir())


def test_workspace_parent_replacement_never_creates_a_child_in_the_replacement(tmp_path, monkeypatch):
    source, bundle, parent = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    retained = tmp_path / "retained-parent"
    original_mkdir = os.mkdir
    replaced = False
    escaped = False

    def mkdir(path, mode=0o777, *args, **kwargs):
        nonlocal replaced, escaped
        if not replaced:
            replaced = True
            parent.rename(retained)
            parent.symlink_to(outside)
        try:
            return original_mkdir(path, mode, *args, **kwargs)
        finally:
            escaped = escaped or bool(list(outside.iterdir()))

    monkeypatch.setattr(os, "mkdir", mkdir)
    with pytest.raises(CandidateWorkspaceError):
        _materialize(source, bundle, parent)
    assert replaced
    assert not escaped
    assert not list(outside.iterdir())
    assert parent.is_symlink()


def test_cleanup_failure_is_explicit_and_leaves_the_partial_child(tmp_path, monkeypatch):
    source, bundle, parent = _fixture(tmp_path)
    original_unlink = os.unlink
    blocked_cleanup = False

    def unlink(path, *args, **kwargs):
        nonlocal blocked_cleanup
        if Path(path).name in {"main.py", "helper.py"}:
            blocked_cleanup = True
            raise OSError("injected private cleanup failure")
        return original_unlink(path, *args, **kwargs)

    def write(*_args, **_kwargs):
        raise OSError("injected private write failure")

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_cleanup_failed$"):
        _materialize(source, bundle, parent)
    assert blocked_cleanup
    assert len(list(parent.iterdir())) == 1
    assert any(path.is_file() for path in parent.rglob("*"))


def test_zero_byte_write_is_a_failure_and_cleans_the_child(tmp_path, monkeypatch):
    source, bundle, parent = _fixture(tmp_path)
    monkeypatch.setattr(os, "write", lambda *_args, **_kwargs: 0)
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_destination_write_failed$"):
        _materialize(source, bundle, parent)
    assert not list(parent.iterdir())


def test_parent_case_alias_cannot_place_workspace_inside_source(tmp_path):
    source, bundle, _ = _fixture(tmp_path)
    alias = source.with_name(source.name.upper())
    if not alias.exists() or alias.stat().st_ino != source.stat().st_ino:
        # Case-sensitive filesystems have no alias here; the ordinary equality case remains covered.
        alias = source
    child = alias / "workspaces"
    child.mkdir()
    with pytest.raises(CandidateWorkspaceError, match=r"^candidate_workspace_workspace_root_unsafe$"):
        _materialize(source, bundle, child)
    assert not list(child.iterdir())


def test_success_does_not_change_source_identity_or_create_control_state(tmp_path):
    source, bundle, parent = _fixture(tmp_path)
    before = {path: (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
              for path in source.rglob("*") if path.is_file()}
    result = _materialize(source, bundle, parent)
    after = {path: (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
             for path in source.rglob("*") if path.is_file()}
    assert before == after
    assert not (result.workspace_path / "state.db").exists()
