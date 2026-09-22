"""Provider-free campaign directory inventory and audit tests."""
from __future__ import annotations

import copy
import hashlib
import os

import pytest

from lunar_evolution.campaign_inventory import (
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
