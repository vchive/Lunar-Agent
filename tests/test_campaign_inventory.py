"""Provider-free campaign directory inventory and audit tests."""
from __future__ import annotations

import copy
import hashlib
import os

import pytest

from lunar_evolution.campaign_inventory import (
    MAX_INVENTORY_DEPTH,
    MAX_INVENTORY_FILE_BYTES,
    CampaignInventoryError,
    audit_campaign_directory,
    inventory_campaign_directory,
)


def _campaign(tmp_path):
    root = tmp_path / "campaign-20260922"
    (root / "evidence").mkdir(parents=True)
    (root / "manifest.json").write_bytes(b'{"scope":"observation"}\n')
    (root / "evidence" / "receipt.json").write_bytes(b'{"stage":"preparation"}\n')
    return root


def test_inventory_is_canonical_and_audit_is_read_only(tmp_path):
    root = _campaign(tmp_path)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    observed = inventory_campaign_directory(root)
    assert observed["file_count"] == 2
    assert observed["total_bytes"] == sum(map(len, before.values()))
    assert observed["files"] == [
        {"path": "evidence/receipt.json", "size": len(before[next(k for k in before if str(k) == "evidence/receipt.json")]), "sha256": hashlib.sha256(before[next(k for k in before if str(k) == "evidence/receipt.json")]).hexdigest()},
        {"path": "manifest.json", "size": len(before[next(k for k in before if str(k) == "manifest.json")]), "sha256": hashlib.sha256(before[next(k for k in before if str(k) == "manifest.json")]).hexdigest()},
    ]
    snapshot = copy.deepcopy(observed)
    assert audit_campaign_directory(root, observed)["status"] == "verified"
    assert observed == snapshot
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_audit_rejects_changed_bytes_and_tampered_expected_digest(tmp_path):
    root = _campaign(tmp_path)
    expected = inventory_campaign_directory(root)
    (root / "manifest.json").write_bytes(b"changed\n")
    with pytest.raises(CampaignInventoryError, match="^inventory_mismatch$"):
        audit_campaign_directory(root, expected)
    tampered = inventory_campaign_directory(root)
    tampered["inventory_sha256"] = "f" * 64
    with pytest.raises(CampaignInventoryError, match="^digest_mismatch$"):
        audit_campaign_directory(root, tampered)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_inventory_rejects_non_regular_files(tmp_path, kind):
    root = _campaign(tmp_path)
    target = root / "evidence" / "bad"
    if kind == "symlink":
        target.symlink_to(root / "manifest.json")
    else:
        os.mkfifo(target)
    with pytest.raises(CampaignInventoryError, match="^file_unsafe$"):
        inventory_campaign_directory(root)


def test_inventory_rejects_oversize_before_reading(tmp_path, monkeypatch):
    root = _campaign(tmp_path)
    source = root / "a-huge.bin"
    with source.open("wb") as stream:
        stream.truncate(MAX_INVENTORY_FILE_BYTES + 1)
    monkeypatch.setattr(os, "read", lambda *_: pytest.fail("oversize bytes were read"))
    with pytest.raises(CampaignInventoryError, match="^file_too_large$"):
        inventory_campaign_directory(root)


def test_inventory_does_not_execute_executable_material(tmp_path):
    root = _campaign(tmp_path)
    script = root / "evidence" / "candidate.py"
    script.write_text("raise SystemExit('must not execute')\n", encoding="utf-8")
    script.chmod(0o755)
    result = inventory_campaign_directory(root)
    assert any(item["path"] == "evidence/candidate.py" for item in result["files"])


def test_inventory_rejects_excessive_directory_depth(tmp_path):
    root = _campaign(tmp_path)
    current = root
    for index in range(MAX_INVENTORY_DEPTH + 2):
        current = current / f"d{index}"
        current.mkdir()
    with pytest.raises(CampaignInventoryError, match="^too_many_files$"):
        inventory_campaign_directory(root)


@pytest.mark.parametrize("change", ["add", "remove", "replace", "late_nested_write"])
def test_inventory_rejects_changes_during_byte_reads(tmp_path, monkeypatch, change):
    root = _campaign(tmp_path)
    nested = root / "evidence" / "receipt.json"
    target = root / "z-target.bin"
    target.write_bytes(b"retained")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"retained")
    old_nested = nested.stat()
    old_directory = nested.parent.stat()
    original_read = os.read
    changed = False
    manifest_identity = (root / "manifest.json").stat().st_ino

    def read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        # manifest is read after the nested directory has already been walked and closed.
        if chunk and not changed and os.fstat(descriptor).st_ino == manifest_identity:
            changed = True
            if change == "add":
                (root / "new.bin").write_bytes(b"new")
            elif change == "remove":
                target.unlink()
            elif change == "replace":
                replacement.replace(target)
            else:
                nested.write_bytes(b"x" * old_nested.st_size)
                os.utime(nested, ns=(old_nested.st_atime_ns, old_nested.st_mtime_ns))
                assert nested.parent.stat().st_mtime_ns == old_directory.st_mtime_ns
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(CampaignInventoryError, match="^root_changed$"):
        inventory_campaign_directory(root)
    assert changed


@pytest.mark.parametrize("fault", ["fstat_error", "identity_mismatch"])
def test_child_descriptor_is_closed_when_initial_fstat_fails(tmp_path, monkeypatch, fault):
    root = _campaign(tmp_path)
    original_open, original_fstat = os.open, os.fstat
    opened = []
    child = None
    failed = False
    replacement = tmp_path / "different-directory"
    replacement.mkdir()
    other_info = replacement.stat()

    def open_file(name, flags, *args, **kwargs):
        nonlocal child
        descriptor = original_open(name, flags, *args, **kwargs)
        opened.append(descriptor)
        if name == "evidence":
            child = descriptor
        return descriptor

    def fstat(descriptor):
        nonlocal failed
        if descriptor == child and not failed:
            failed = True
            if fault == "fstat_error":
                raise OSError("private diagnostic must not escape")
            return other_info
        return original_fstat(descriptor)

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(CampaignInventoryError) as error:
        inventory_campaign_directory(root)
    assert error.value.code in {"file_unsafe", "root_changed"}
    assert failed
    for descriptor in opened:
        with pytest.raises(OSError):
            original_fstat(descriptor)


def test_renamed_root_maps_directory_chain_error_to_inventory_error(tmp_path, monkeypatch):
    root = _campaign(tmp_path)
    original_read = os.read
    changed = False

    def read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            root.rename(root.with_name("retained"))
            root.mkdir()
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(CampaignInventoryError, match="^root_changed$"):
        inventory_campaign_directory(root)
    assert changed


@pytest.mark.parametrize("kind", ["missing", "linked"])
def test_root_failures_use_fixed_inventory_errors(tmp_path, kind):
    root = tmp_path / "campaign-root"
    if kind == "linked":
        target = tmp_path / "target"
        target.mkdir()
        root.symlink_to(target, target_is_directory=True)
    with pytest.raises(CampaignInventoryError, match="^root_" + ("missing" if kind == "missing" else "unsafe") + "$"):
        inventory_campaign_directory(root)


def test_entry_limit_stops_scandir_before_materializing_all_names(tmp_path, monkeypatch):
    from lunar_evolution import campaign_inventory as module

    root = tmp_path / "campaign-root"
    root.mkdir()
    for index in range(20):
        (root / f"d{index}").mkdir()
    monkeypatch.setattr(module, "MAX_INVENTORY_ENTRIES", 3)
    original_scandir = os.scandir
    visited = 0

    class CountEntries:
        def __init__(self, path):
            self.iterator = original_scandir(path)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.iterator.close()

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal visited
            item = next(self.iterator)
            visited += 1
            return item

    monkeypatch.setattr(os, "scandir", CountEntries)
    with pytest.raises(CampaignInventoryError, match="^too_many_entries$"):
        inventory_campaign_directory(root)
    assert visited == 4


def test_entry_limit_counts_empty_directories_across_entire_tree(tmp_path, monkeypatch):
    from lunar_evolution import campaign_inventory as module

    root = tmp_path / "campaign-root"
    (root / "a" / "nested").mkdir(parents=True)
    (root / "b" / "nested").mkdir(parents=True)
    monkeypatch.setattr(module, "MAX_INVENTORY_ENTRIES", 4)
    assert inventory_campaign_directory(root)["file_count"] == 0
    monkeypatch.setattr(module, "MAX_INVENTORY_ENTRIES", 3)
    with pytest.raises(CampaignInventoryError, match="^too_many_entries$"):
        inventory_campaign_directory(root)


def test_depth_limit_accepts_boundary_and_rejects_one_more_directory(tmp_path, monkeypatch):
    from lunar_evolution import campaign_inventory as module

    root = tmp_path / "campaign-root"
    (root / "a" / "b").mkdir(parents=True)
    monkeypatch.setattr(module, "MAX_INVENTORY_DEPTH", 2)
    assert inventory_campaign_directory(root)["file_count"] == 0
    (root / "a" / "b" / "c").mkdir()
    with pytest.raises(CampaignInventoryError, match="^too_many_files$"):
        inventory_campaign_directory(root)
