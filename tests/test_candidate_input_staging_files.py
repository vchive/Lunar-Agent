"""Local filesystem boundaries for staging declared candidate execution inputs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from lunar_evolution.candidate_bundle import CandidateSourceBundle
from lunar_evolution.candidate_execution import (
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    build_candidate_execution_admission,
)
from lunar_evolution.candidate_input_staging import (
    CandidateInputStagingError,
    stage_candidate_execution_inputs,
)
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan


def _fixture(tmp_path: Path, *, contents=None):
    source = tmp_path / "inputs"
    source.mkdir()
    contents = {"data/input.bin": b"fixture"} if contents is None else contents
    for target, content in contents.items():
        path = source / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    bundle = CandidateSourceBundle.from_dict({
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": "a" * 64, "entrypoint": "main.py",
        "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    })
    plan = build_candidate_workspace_plan(
        bundle, contract_sha256="a" * 64, command=["/absent/runner", "main.py"],
        timeout_seconds=5, max_output_bytes=1024,
    )
    admission = build_candidate_execution_admission(
        plan,
        inputs=[CandidateExecutionInput(target, "fixture", len(content), hashlib.sha256(content).hexdigest())
                for target, content in contents.items()],
        dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("exact-harness", "d" * 64),
        output_contract_sha256="e" * 64,
        budget=CandidateExecutionBudget(5, 1024, 1024, 1),
    )
    parent = tmp_path / "staged-inputs"
    parent.mkdir()
    return source, parent, plan, admission


def _stage(source, parent, plan, admission):
    return stage_candidate_execution_inputs(
        admission, plan=plan, input_root=source, staging_root=parent,
    )


def _identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def test_private_tree_copies_only_declared_binary_nested_and_empty_inputs(tmp_path):
    contents = {"data/input.bin": b"\x00\xff\x80private payload", "empty": b""}
    source, parent, plan, admission = _fixture(tmp_path, contents=contents)
    (source / "undeclared").symlink_to(tmp_path / "missing")
    sibling = parent / "existing-child"
    sibling.mkdir()
    (sibling / "retained").write_bytes(b"existing bytes")
    before = {target: (source / target).stat() for target in contents}

    result = _stage(source, parent, plan, admission)

    assert result.input_path.parent == parent
    assert result.input_path.stat().st_mode & 0o777 == 0o700
    assert (result.input_path / "data").stat().st_mode & 0o777 == 0o700
    assert sorted(path.relative_to(result.input_path).as_posix() for path in result.input_path.rglob("*")) == [
        "data", "data/input.bin", "empty",
    ]
    for target, content in contents.items():
        staged = result.input_path / target
        assert staged.read_bytes() == content
        assert staged.stat().st_mode & 0o777 == 0o600
        assert _identity(staged) != _identity(source / target)
        after = (source / target).stat()
        original = before[target]
        assert (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
            original.st_ino, original.st_size, original.st_mtime_ns, original.st_ctime_ns,
        )
    assert (sibling / "retained").read_bytes() == b"existing bytes"
    assert "private payload" not in str(result.to_dict())
    assert str(tmp_path) not in str(result.to_dict())


@pytest.mark.parametrize("kind", ["file-link", "directory", "fifo"])
def test_input_leaves_must_be_regular_non_symlink_files(tmp_path, kind):
    source, parent, plan, admission = _fixture(tmp_path)
    path = source / "data/input.bin"
    path.unlink()
    if kind == "file-link":
        outside = tmp_path / "outside"
        outside.write_bytes(b"fixture")
        path.symlink_to(outside)
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_input_unsafe$"):
        _stage(source, parent, plan, admission)
    assert list(parent.iterdir()) == []


def test_source_hardlink_is_copied_into_an_independent_single_link_file(tmp_path):
    source, parent, plan, admission = _fixture(tmp_path)
    path = source / "data/input.bin"
    alias = tmp_path / "source-hardlink"
    os.link(path, alias)
    assert path.stat().st_nlink == 2

    result = _stage(source, parent, plan, admission)

    staged = result.input_path / "data/input.bin"
    assert staged.read_bytes() == b"fixture"
    assert staged.stat().st_nlink == 1
    assert _identity(staged) != _identity(path)
    assert _identity(alias) == _identity(path)


@pytest.mark.parametrize("level", ["root", "ancestor", "input-directory"])
def test_symlink_components_of_source_are_not_followed(tmp_path, level):
    source, parent, plan, admission = _fixture(tmp_path)
    if level == "root":
        alias = tmp_path / "alias"
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif level == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        source = alias / source.name
    else:
        retained = tmp_path / "retained-data"
        (source / "data").rename(retained)
        (source / "data").symlink_to(retained, target_is_directory=True)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_input_unsafe$"):
        _stage(source, parent, plan, admission)
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize(("content", "error"), [
    (None, "input_missing"), (b"", "input_changed"),
    (b"fixture-extra", "input_changed"), (b"fixturE", "input_changed"),
])
def test_missing_changed_and_oversized_inputs_are_rejected_without_a_tree(tmp_path, content, error):
    source, parent, plan, admission = _fixture(tmp_path)
    path = source / "data/input.bin"
    if content is None:
        path.unlink()
    else:
        path.write_bytes(content)
    with pytest.raises(CandidateInputStagingError, match=f"^candidate_input_staging_{error}$"):
        _stage(source, parent, plan, admission)
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "file", "link", "fifo", "ancestor-link"])
def test_empty_input_sets_still_require_a_physical_input_root(tmp_path, kind):
    source, parent, plan, admission = _fixture(tmp_path, contents={})
    source.rmdir()
    if kind == "file":
        source.write_bytes(b"")
    elif kind == "link":
        source.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "ancestor-link":
        source.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        source = alias / source.name
    error = "input_missing" if kind == "missing" else "input_unsafe"
    with pytest.raises(CandidateInputStagingError, match=f"^candidate_input_staging_{error}$"):
        _stage(source, parent, plan, admission)
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "file", "link", "fifo", "ancestor-link"])
def test_staging_parent_must_be_existing_physical_directory_even_without_inputs(tmp_path, kind):
    source, parent, plan, admission = _fixture(tmp_path, contents={})
    parent.rmdir()
    if kind == "file":
        parent.write_bytes(b"")
    elif kind == "link":
        parent.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(parent)
    elif kind == "ancestor-link":
        parent.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        parent = alias / parent.name
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_staging_root_unsafe$"):
        _stage(source, parent, plan, admission)


@pytest.mark.parametrize("root", ["input", "staging"])
def test_parent_traversal_components_are_not_normalized_away(tmp_path, root):
    source, parent, plan, admission = _fixture(tmp_path)
    if root == "input":
        source = source / "absent" / ".."
    else:
        parent = parent / "absent" / ".."
    error = "input_unsafe" if root == "input" else "staging_root_unsafe"
    with pytest.raises(CandidateInputStagingError, match=f"^candidate_input_staging_{error}$"):
        _stage(source, parent, plan, admission)


@pytest.mark.parametrize("relation", ["same", "staging-inside-source", "source-inside-staging"])
def test_source_and_staging_roots_must_be_disjoint(tmp_path, relation):
    source, parent, plan, admission = _fixture(tmp_path)
    if relation == "same":
        parent = source
    elif relation == "staging-inside-source":
        parent = source / "stages"
        parent.mkdir()
    else:
        parent = tmp_path
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_staging_root_unsafe$"):
        _stage(source, parent, plan, admission)
    assert (source / "data/input.bin").read_bytes() == b"fixture"


@pytest.mark.parametrize("relation", ["same", "staging-inside-source", "source-inside-staging"])
def test_case_alias_directory_identity_cannot_bypass_overlap_detection(tmp_path, relation):
    source, parent, plan, admission = _fixture(tmp_path)
    alias = source.with_name(source.name.upper())
    if not alias.exists() or _identity(alias) != _identity(source):
        pytest.skip("filesystem does not expose a distinct case alias")
    if relation == "same":
        parent = alias
    elif relation == "staging-inside-source":
        parent = alias / "stages"
        parent.mkdir()
    else:
        child = source / "child"
        child.mkdir()
        (source / "data").rename(child / "data")
        source = child
        parent = alias
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_staging_root_unsafe$"):
        _stage(source, parent, plan, admission)
    assert (source / "data/input.bin").read_bytes() == b"fixture"


@pytest.mark.parametrize("mutation", ["replace-leaf", "modify-leaf", "replace-directory", "delete-leaf"])
def test_source_mutation_during_bounded_read_is_rejected(tmp_path, monkeypatch, mutation):
    source, parent, plan, admission = _fixture(tmp_path)
    path = source / "data/input.bin"
    source_identity = _identity(path)
    original_read = os.read
    changed = False

    def read_and_mutate(descriptor, count):
        nonlocal changed
        info = os.fstat(descriptor)
        content = original_read(descriptor, count)
        if not changed and (info.st_dev, info.st_ino) == source_identity:
            changed = True
            if mutation == "replace-leaf":
                replacement = path.with_name("replacement")
                replacement.write_bytes(b"fixture")
                replacement.replace(path)
            elif mutation == "modify-leaf":
                path.write_bytes(b"fixturE")
            elif mutation == "replace-directory":
                (source / "data").rename(source / "retained-data")
                (source / "data").mkdir()
                path.write_bytes(b"fixture")
            else:
                path.unlink()
        return content

    monkeypatch.setattr(os, "read", read_and_mutate)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_input_changed$"):
        _stage(source, parent, plan, admission)
    assert changed
    assert list(parent.iterdir()) == []


def test_oversized_source_is_rejected_before_reading_its_bytes(tmp_path, monkeypatch):
    source, parent, plan, admission = _fixture(tmp_path)
    (source / "data/input.bin").write_bytes(b"fixture-extra")
    monkeypatch.setattr(os, "read", lambda *_a, **_kw: pytest.fail("oversized source was read"))
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_input_changed$"):
        _stage(source, parent, plan, admission)
    assert list(parent.iterdir()) == []


def test_destination_is_rehashed_even_when_corruption_preserves_size_and_inode(tmp_path, monkeypatch):
    source, parent, plan, admission = _fixture(tmp_path)
    original_write = os.write
    corrupted = False

    def write_corrupted(descriptor, data):
        nonlocal corrupted
        corrupted = True
        return original_write(descriptor, b"X" * len(data))

    monkeypatch.setattr(os, "write", write_corrupted)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_destination_changed$"):
        _stage(source, parent, plan, admission)
    assert corrupted
    assert list(parent.iterdir()) == []
    assert (source / "data/input.bin").read_bytes() == b"fixture"


@pytest.mark.parametrize("failure", ["raise", "zero", "after-partial-write"])
def test_write_failure_cleans_only_the_new_tree_and_has_a_fixed_error(tmp_path, monkeypatch, failure):
    source, parent, plan, admission = _fixture(tmp_path)
    sibling = parent / "existing"
    sibling.mkdir()
    (sibling / "retained").write_bytes(b"retained")
    original_write = os.write
    writes = 0

    def fail_write(descriptor, data):
        nonlocal writes
        writes += 1
        if failure == "zero":
            return 0
        if failure == "after-partial-write" and writes == 1:
            return original_write(descriptor, data[:1])
        raise OSError(f"private operating system error at {tmp_path}")

    monkeypatch.setattr(os, "write", fail_write)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_destination_write_failed$"):
        _stage(source, parent, plan, admission)
    assert writes == (2 if failure == "after-partial-write" else 1)
    assert list(parent.iterdir()) == [sibling]
    assert (sibling / "retained").read_bytes() == b"retained"
    assert (source / "data/input.bin").read_bytes() == b"fixture"


def test_keyboard_interrupt_cleans_partial_tree_then_propagates(tmp_path, monkeypatch):
    source, parent, plan, admission = _fixture(tmp_path)
    original_write = os.write

    def interrupted_write(descriptor, data):
        original_write(descriptor, data[:1])
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "write", interrupted_write)
    with pytest.raises(KeyboardInterrupt):
        _stage(source, parent, plan, admission)
    assert list(parent.iterdir()) == []
    assert (source / "data/input.bin").read_bytes() == b"fixture"


@pytest.mark.parametrize("root", ["input", "staging"])
def test_interruption_while_opening_directory_chain_closes_acquired_descriptors(tmp_path, monkeypatch, root):
    source, parent, plan, admission = _fixture(tmp_path)
    interrupted_name = source.name if root == "input" else parent.name
    original_open, original_close = os.open, os.close
    opened = []
    closed = []
    interrupted = False

    def open_directory(path, flags, *args, **kwargs):
        nonlocal interrupted
        if Path(path).name == interrupted_name and kwargs.get("dir_fd") is not None:
            interrupted = True
            raise KeyboardInterrupt
        descriptor = original_open(path, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", open_directory)
        patch.setattr(os, "close", close)
        with pytest.raises(KeyboardInterrupt):
            _stage(source, parent, plan, admission)
    assert interrupted
    assert opened
    assert sorted(closed) == sorted(opened)
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("initial_failure", [OSError, KeyboardInterrupt])
def test_cleanup_failure_is_reported_without_os_detail(tmp_path, monkeypatch, initial_failure):
    source, parent, plan, admission = _fixture(tmp_path)
    original_unlink = os.unlink
    cleanup_attempted = False

    def unlink(path, *args, **kwargs):
        nonlocal cleanup_attempted
        if Path(path).name == "input.bin":
            cleanup_attempted = True
            raise OSError(f"cannot unlink private path {tmp_path}")
        return original_unlink(path, *args, **kwargs)

    def write(*_args, **_kwargs):
        raise initial_failure("injected write interruption")

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_cleanup_failed$"):
        _stage(source, parent, plan, admission)
    assert cleanup_attempted
    assert len(list(parent.iterdir())) == 1
    assert len(list(parent.rglob("input.bin"))) == 1
    assert (source / "data/input.bin").read_bytes() == b"fixture"


@pytest.mark.parametrize("level", ["file", "directory", "root"])
def test_cleanup_preserves_foreign_replacements_instead_of_deleting_them(tmp_path, monkeypatch, level):
    source, parent, plan, admission = _fixture(tmp_path)
    replacement = None

    def replace_then_fail(*_args, **_kwargs):
        nonlocal replacement
        tree = next(parent.iterdir())
        original = tree / "data/input.bin" if level == "file" else tree / "data" if level == "directory" else tree
        original.rename(tmp_path / "retained-owned-node")
        if level == "file":
            replacement = original
        else:
            original.mkdir()
            replacement = original / "foreign-sentinel"
        replacement.write_bytes(b"foreign bytes must remain")
        raise OSError("injected failure after replacement")

    monkeypatch.setattr(os, "write", replace_then_fail)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_cleanup_failed$"):
        _stage(source, parent, plan, admission)
    assert replacement is not None
    assert replacement.read_bytes() == b"foreign bytes must remain"
    assert (source / "data/input.bin").read_bytes() == b"fixture"


def test_cleanup_does_not_delete_an_untracked_destination_entry(tmp_path, monkeypatch):
    source, parent, plan, admission = _fixture(tmp_path)
    foreign = None

    def add_foreign_then_fail(*_args, **_kwargs):
        nonlocal foreign
        foreign = next(parent.iterdir()) / "foreign"
        foreign.write_bytes(b"foreign bytes")
        raise OSError("injected failure after foreign addition")

    monkeypatch.setattr(os, "write", add_foreign_then_fail)
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_cleanup_failed$"):
        _stage(source, parent, plan, admission)
    assert foreign is not None
    assert foreign.read_bytes() == b"foreign bytes"


def test_staging_parent_replacement_never_writes_into_the_foreign_target(tmp_path, monkeypatch):
    source, parent, plan, admission = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    retained = tmp_path / "retained-parent"
    original_mkdir = os.mkdir
    changed = False
    escaped = False

    def mkdir(path, mode=0o777, *args, **kwargs):
        nonlocal changed, escaped
        if not changed:
            changed = True
            parent.rename(retained)
            parent.symlink_to(outside, target_is_directory=True)
        try:
            return original_mkdir(path, mode, *args, **kwargs)
        finally:
            escaped = escaped or bool(list(outside.iterdir()))

    monkeypatch.setattr(os, "mkdir", mkdir)
    with pytest.raises(CandidateInputStagingError):
        _stage(source, parent, plan, admission)
    assert changed
    assert not escaped
    assert list(outside.iterdir()) == []
    assert parent.is_symlink()
    assert (source / "data/input.bin").read_bytes() == b"fixture"
