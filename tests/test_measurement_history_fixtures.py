"""Portable history tests retain the actual byte, path, and final-seal rejection rules."""

import importlib.util
import json
from pathlib import Path

import pytest
from measurement_history_fixtures import prepare_history_fixture

ROOT = Path(__file__).resolve().parents[1]
FEATURES = (
    "076-public-plan-handoff-measurement",
    "078-master-planning-role-measurement",
    "082-http-deadline-measurement",
)


@pytest.fixture(params=FEATURES)
def history_audit(request):
    path = ROOT / "specs" / request.param / "measurement/adapter.py"
    spec = importlib.util.spec_from_file_location("portable_history_adapter", path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter.load_current("audit")


def copy_files(relative_paths, destination):
    for relative in relative_paths:
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())


def reseal_synthetic_manifest(audit, fixture_root, manifest):
    manifest_relative = audit.PRIOR_ROOT + "/measurement/manifest.json"
    final_relative = audit.PRIOR_ROOT + "/postrun/final-audit.json"
    manifest_path = fixture_root / manifest_relative
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = audit.sha(manifest_path)
    audit.SEALED_HISTORY[manifest_relative] = digest
    final = audit.read(fixture_root / final_relative)
    final["manifest_sha256"] = digest
    (fixture_root / final_relative).write_text(json.dumps(final), encoding="utf-8")
    audit.SEALED_HISTORY[final_relative] = audit.sha(fixture_root / final_relative)


def test_portable_history_never_reads_real_private_campaigns(history_audit, tmp_path, monkeypatch):
    original_open = Path.open

    def reject_private_inventory(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(ROOT / ".lunar"), "test read real private inventory"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_private_inventory)
    fixture_root = prepare_history_fixture(history_audit, ROOT, tmp_path, monkeypatch)
    history = history_audit.historical_map(fixture_root)
    assert set(history_audit.SEALED_HISTORY) < set(history)
    assert any(relative.startswith(".lunar/") for relative in history)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_portable_history_still_checks_actual_registered_seal_bytes(history_audit, tmp_path, monkeypatch, damage):
    checkout = tmp_path / "tracked-checkout"
    copy_files(history_audit.SEALED_HISTORY, checkout)
    manifest = checkout / history_audit.PRIOR_ROOT / "measurement/manifest.json"
    if damage == "missing":
        manifest.unlink()
    else:
        manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(history_audit.AuditError, match="regular frozen file|digest mismatch"):
        prepare_history_fixture(history_audit, checkout, tmp_path / "fixture", monkeypatch)


@pytest.mark.parametrize("damage", ["missing", "changed", "symlink"])
def test_synthetic_history_keeps_dependency_byte_and_path_guards(history_audit, tmp_path, monkeypatch, damage):
    fixture_root = prepare_history_fixture(history_audit, ROOT, tmp_path / "fixture", monkeypatch)
    manifest = history_audit.read(fixture_root / history_audit.PRIOR_ROOT / "measurement/manifest.json")
    dependency = fixture_root / next(iter(manifest["historical_files_sha256"]))
    if damage == "missing":
        dependency.unlink()
    elif damage == "changed":
        dependency.write_bytes(dependency.read_bytes() + b"changed")
    else:
        outside = tmp_path / "outside.json"
        outside.write_bytes(dependency.read_bytes())
        dependency.unlink()
        dependency.symlink_to(outside)
    with pytest.raises(history_audit.AuditError, match="regular frozen file|digest mismatch|linked evidence"):
        history_audit.historical_map(fixture_root)


@pytest.mark.parametrize("mapping,reason", [
    ({"../escape.json": "a" * 64}, "escaped repository"),
    ({"context.json": "invalid-digest"}, "invalid frozen digest"),
])
def test_synthetic_history_rejects_invalid_dependency_maps(history_audit, tmp_path, monkeypatch, mapping, reason):
    fixture_root = prepare_history_fixture(history_audit, ROOT, tmp_path, monkeypatch)
    manifest = history_audit.read(fixture_root / history_audit.PRIOR_ROOT / "measurement/manifest.json")
    manifest["historical_files_sha256"] = mapping
    reseal_synthetic_manifest(history_audit, fixture_root, manifest)
    with pytest.raises(history_audit.AuditError, match=reason):
        history_audit.historical_map(fixture_root)


@pytest.mark.parametrize("field,value", [
    ("passed", False), ("complete", False), ("final_acceptance", False),
    ("manifest_sha256", "a" * 64),
])
def test_synthetic_history_checks_resealed_final_acceptance_semantics(history_audit, tmp_path, monkeypatch, field, value):
    fixture_root = prepare_history_fixture(history_audit, ROOT, tmp_path, monkeypatch)
    relative = history_audit.PRIOR_ROOT + "/postrun/final-audit.json"
    final_path = fixture_root / relative
    final = history_audit.read(final_path)
    final[field] = value
    final_path.write_text(json.dumps(final), encoding="utf-8")
    history_audit.SEALED_HISTORY[relative] = history_audit.sha(final_path)
    with pytest.raises(history_audit.AuditError, match="matching final seal"):
        history_audit.historical_map(fixture_root)


def test_original_history_check_rejects_a_checkout_without_private_inventory(history_audit, tmp_path):
    manifest = history_audit.read(ROOT / history_audit.PRIOR_ROOT / "measurement/manifest.json")
    tracked = {relative for relative in manifest["historical_files_sha256"] if relative.startswith("specs/")}
    copy_files(tracked | set(history_audit.SEALED_HISTORY), tmp_path)
    with pytest.raises(history_audit.AuditError, match="expected regular frozen file"):
        history_audit.historical_map(tmp_path)
