"""Offline bundle validation observes bounded regular-file bytes without following links."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from famou.candidate_bundle import (
    CandidateBundleError,
    parse_candidate_source_bundle,
    verify_candidate_source_bundle,
)

CONTRACT_SHA = "a" * 64
MANIFEST_LIMIT = 128 * 1024


def _fixture(tmp_path, content=b"VALUE = 42\n"):
    root = tmp_path / "source"
    (root / "pkg").mkdir(parents=True)
    source = root / "pkg" / "main.py"
    source.write_bytes(content)
    payload = {
        "schema_version": "1",
        "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT_SHA,
        "entrypoint": "pkg/main.py",
        "files": [{
            "path": "pkg/main.py",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }],
    }
    return root, source, payload


def _verify(payload, root):
    return verify_candidate_source_bundle(
        payload, source_root=root, contract_sha256=CONTRACT_SHA,
    )


def test_manifest_oversize_is_rejected_before_reading(tmp_path, monkeypatch):
    source = tmp_path / "manifest.json"
    with source.open("wb") as stream:
        stream.truncate(MANIFEST_LIMIT + 1)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("unbounded read_bytes"))
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("oversize manifest was read"))
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_too_large$"):
        parse_candidate_source_bundle(source)


@pytest.mark.parametrize("kind", ["directory", "fifo", "symlink", "missing"])
def test_manifest_rejects_non_regular_files_without_reading(tmp_path, monkeypatch, kind):
    source = tmp_path / "manifest.json"
    if kind == "directory":
        source.mkdir()
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "symlink":
        target = tmp_path / "target.json"
        target.write_bytes(b"{}")
        source.symlink_to(target)
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("invalid manifest was read"))
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(source)


def test_manifest_ancestor_link_is_rejected(tmp_path):
    _, _, payload = _fixture(tmp_path)
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(linked / source.name)


@pytest.mark.parametrize("source", [None, 42, "bad\x00path", "bad\ud800path"])
def test_invalid_manifest_paths_keep_fixed_errors(source):
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(source)


@pytest.mark.parametrize("kind", ["missing", "directory", "fifo", "file_link", "ancestor_link"])
def test_source_rejects_bad_nodes_without_reading(tmp_path, monkeypatch, kind):
    root, source, payload = _fixture(tmp_path)
    if kind == "ancestor_link":
        directory = source.parent
        retained = directory.with_name("retained")
        directory.rename(retained)
        directory.symlink_to(retained)
    else:
        source.unlink()
        if kind == "directory":
            source.mkdir()
        elif kind == "fifo":
            os.mkfifo(source)
        elif kind == "file_link":
            source.symlink_to(tmp_path / "missing")
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("invalid source was read"))
    reason = "source_missing" if kind == "missing" else "source_unsafe"
    with pytest.raises(CandidateBundleError, match=f"^candidate_bundle_{reason}$"):
        _verify(payload, root)


@pytest.mark.parametrize("kind", ["missing", "file", "fifo", "link"])
def test_source_root_must_be_a_directory(tmp_path, monkeypatch, kind):
    _, _, payload = _fixture(tmp_path)
    root = tmp_path / "other"
    if kind == "file":
        root.write_bytes(b"bytes")
    elif kind == "fifo":
        os.mkfifo(root)
    elif kind == "link":
        root.symlink_to(tmp_path / "source")
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("invalid root was read"))
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_root_unsafe$"):
        _verify(payload, root)


@pytest.mark.parametrize("root", [None, 42, "bad\x00path", "bad\ud800path"])
def test_invalid_source_root_has_fixed_error(tmp_path, monkeypatch, root):
    _, _, payload = _fixture(tmp_path)
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("invalid root was read"))
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_root_unsafe$"):
        _verify(payload, root)


def test_source_root_above_ancestor_link_is_rejected(tmp_path):
    root, _, payload = _fixture(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_source_unsafe$"):
        _verify(payload, linked / root.name)


@pytest.mark.parametrize("component", ["file", "directory", "root"])
@pytest.mark.parametrize("replacement", ["symlink", "same_bytes"])
def test_substitution_before_open_is_rejected(tmp_path, monkeypatch, component, replacement):
    root, source, payload = _fixture(tmp_path)
    target = source if component == "file" else source.parent if component == "directory" else root
    saved = target.with_name("retained")
    substitute = tmp_path / "replacement"
    content = source.read_bytes()
    if component == "file":
        substitute.write_bytes(content)
    else:
        child = substitute / source.relative_to(target)
        child.parent.mkdir(parents=True)
        child.write_bytes(content)
    original_open = os.open
    changed = False

    def fd_open(name, flags, *args, **kwargs):
        nonlocal changed
        if not changed and str(name) == target.name:
            changed = True
            target.rename(saved)
            if replacement == "symlink":
                target.symlink_to(substitute)
            else:
                substitute.rename(target)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fd_open)
    with pytest.raises(CandidateBundleError):
        _verify(payload, root)
    assert changed


@pytest.mark.parametrize("change", ["replace", "rewrite", "grow", "delete", "directory", "root"])
def test_observed_changes_during_source_read_are_rejected(tmp_path, monkeypatch, change):
    root, source, payload = _fixture(tmp_path)
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
                replacement = source.with_name("replacement.py")
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
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_source_changed$"):
        _verify(payload, root)
    assert changed


def test_manifest_replacement_during_read_is_rejected(tmp_path, monkeypatch):
    _, _, payload = _fixture(tmp_path)
    source = tmp_path / "manifest.json"
    content = json.dumps(payload).encode("utf-8")
    source.write_bytes(content)
    original_read = os.read
    changed = False

    def read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            replacement = source.with_name("replacement.json")
            replacement.write_bytes(content)
            replacement.replace(source)
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(source)
    assert changed


@pytest.mark.parametrize("actual_size", [0, 100, 1024 * 1024 + 1])
def test_source_size_mismatch_is_rejected_before_read(tmp_path, monkeypatch, actual_size):
    root, source, payload = _fixture(tmp_path)
    with source.open("wb") as stream:
        stream.truncate(actual_size)
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("size-mismatched source was read"))
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_source_changed$"):
        _verify(payload, root)


def test_source_reads_are_bounded_by_declared_size(tmp_path, monkeypatch):
    content = b"#" * (256 * 1024)
    root, _, payload = _fixture(tmp_path, content)
    original_read = os.read
    sizes = []

    def read(descriptor, size):
        sizes.append(size)
        return original_read(descriptor, size)

    monkeypatch.setattr(os, "read", read)
    monkeypatch.setattr(Path, "read_bytes", lambda *_: pytest.fail("unbounded read_bytes"))
    assert _verify(payload, root).total_bytes == len(content)
    assert sizes
    assert max(sizes) <= 64 * 1024
    assert sum(sizes) <= len(content) + 1


def test_manifest_reads_are_bounded(tmp_path, monkeypatch):
    source = tmp_path / "manifest.json"
    source.write_bytes(b" " * MANIFEST_LIMIT)
    original_read = os.read
    sizes = []

    def read(descriptor, size):
        sizes.append(size)
        return original_read(descriptor, size)

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(CandidateBundleError, match="^candidate_bundle_invalid$"):
        parse_candidate_source_bundle(source)
    assert sizes
    assert max(sizes) <= 64 * 1024
    assert sum(sizes) <= MANIFEST_LIMIT + 1


@pytest.mark.parametrize("valid", [True, False])
def test_opened_descriptors_are_closed(tmp_path, monkeypatch, valid):
    root, source, payload = _fixture(tmp_path)
    if not valid:
        source.write_bytes(b"bad size")
    original_open = os.open
    opened = []

    def track_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", track_open)
    if valid:
        _verify(payload, root)
    else:
        with pytest.raises(CandidateBundleError):
            _verify(payload, root)
    assert opened
    for descriptor in set(opened):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_verification_preserves_source_bytes_names_and_metadata(tmp_path):
    root, source, payload = _fixture(tmp_path)
    (root / "undeclared.txt").write_text("not part of the source manifest", encoding="utf-8")
    names = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    content = source.read_bytes()
    before = source.stat()
    assert _verify(payload, root).bundle == parse_candidate_source_bundle(payload)
    assert source.read_bytes() == content
    after = source.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*")) == names
