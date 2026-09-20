"""Persistent Feature 139 registration and one-slot admission stay offline."""
from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "feature139_registration_store"
PACKAGE_ROOT = ROOT / "specs/139-real-multifile-closure/measurement"
package_spec = importlib.util.spec_from_file_location(
    PACKAGE, PACKAGE_ROOT / "__init__.py", submodule_search_locations=[str(PACKAGE_ROOT)],
)
package = importlib.util.module_from_spec(package_spec)
sys.modules[PACKAGE] = package
assert package_spec.loader is not None
package_spec.loader.exec_module(package)
campaign = importlib.import_module(f"{PACKAGE}.campaign")
registration = importlib.import_module(f"{PACKAGE}.registration")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    files = {
        "src/product.py": "VALUE = 1\n",
        "pyproject.toml": "[project]\nname = 'registration-fixture'\n",
        "fixture/measurement.py": "MEASUREMENT = 1\n",
        "fixture/history.json": "{}\n",
        "fixture/prior.json": json.dumps({
            "registration_id": "registration-prior",
            "campaign_id": "campaign-prior",
            "campaign_root": ".lunar/prior",
        }, sort_keys=True) + "\n",
        ".gitignore": ".lunar/\n",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    git(tmp_path, "add", ".")
    git(
        tmp_path, "-c", "user.name=Offline139", "-c",
        "user.email=offline139@example.invalid", "commit", "-qm", "fixture base",
    )
    base = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    monkeypatch.setattr(campaign, "PRODUCT_COMMIT", base)
    contract = registration.fixed_contract()
    contract["campaign_root"] = ".lunar/registration-fixture"
    contract["registration_id"] = "registration-fixture-139"
    contract["campaign_id"] = "campaign-fixture-139"
    provider = copy.deepcopy(contract["provider_safe_metadata"])
    store = registration.RegistrationRepository(
        repo=tmp_path,
        manifest_path=tmp_path / "fixture/manifest.json",
        expected_contract=contract,
        measurement_names=("fixture/measurement.py",),
        historical_names=("fixture/history.json", "fixture/prior.json"),
        prior_manifest_names=("fixture/prior.json",),
        provider_probe=lambda: copy.deepcopy(provider),
        runtime_probe=lambda: {"runtime": "offline-fixture"},
        now=lambda: "2026-09-20T00:00:00+00:00",
    )
    return store, provider, base


@pytest.fixture
def registered(repository):
    store, provider, base = repository
    result = store.register()
    return store, provider, base, result


def commit_registration(store) -> str:
    git(store.repo, "add", store.manifest_name)
    git(
        store.repo, "-c", "user.name=Offline139", "-c",
        "user.email=offline139@example.invalid", "commit", "-qm", "fixture registration",
    )
    head = git(store.repo, "rev-parse", "HEAD")
    git(store.repo, "update-ref", "refs/remotes/origin/main", head)
    return head


def test_registration_is_canonical_exclusive_and_exact(registered):
    store, _provider, base, result = registered
    raw = store.manifest_path.read_bytes()
    manifest = json.loads(raw)
    assert raw == registration.canonical_bytes(manifest)
    assert stat.S_IMODE(store.manifest_path.stat().st_mode) == 0o600
    assert result == {
        "status": "registered",
        "manifest_sha256": registration.sha256_bytes(raw),
        "model_calls": 0,
    }
    assert manifest["registration_base_commit"] == base
    assert set(manifest["product_files"]) == {"pyproject.toml", "src/product.py"}
    assert set(manifest["measurement_files"]) == {"fixture/measurement.py"}
    assert set(manifest["historical_files"]) == {"fixture/history.json", "fixture/prior.json"}
    assert "api_key" not in json.dumps(manifest["provider_safe_metadata"])
    with pytest.raises(registration.RegistrationStoreError, match="registration_already_exists"):
        store.register()


def test_committed_git_bytes_are_the_launch_trust_root(registered):
    store, _provider, _base, _result = registered
    head = commit_registration(store)
    verified = store.verify_launch()
    committed = subprocess.check_output(
        ["git", "show", f"HEAD:{store.manifest_name}"], cwd=store.repo,
    )
    assert verified.registration_commit == head
    assert verified.manifest_sha256 == registration.sha256_bytes(committed)


@pytest.mark.parametrize("field", ("registration_id", "campaign_id", "budgets"))
def test_forged_identity_or_budget_with_recomputed_digest_is_rejected(registered, field):
    store, _provider, _base, _result = registered
    value = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    if field == "budgets":
        value[field]["candidate_steps"] = 99
    else:
        value[field] = f"forged-{field}"
    store.manifest_path.write_bytes(registration.canonical_bytes(value))
    forged_digest = registration.sha256_bytes(store.manifest_path.read_bytes())
    assert len(forged_digest) == 64
    with pytest.raises(registration.RegistrationStoreError, match="fixed_contract_changed"):
        store.verify()


@pytest.mark.parametrize("group", ("product", "measurement", "historical"))
def test_mutated_registered_file_is_rejected(registered, group):
    store, _provider, _base, _result = registered
    paths = {
        "product": store.repo / "src/product.py",
        "measurement": store.repo / "fixture/measurement.py",
        "historical": store.repo / "fixture/history.json",
    }
    paths[group].write_text("MUTATED = 1\n", encoding="utf-8")
    error = "product_bytes_changed" if group == "product" else f"{group}_files_changed"
    with pytest.raises(registration.RegistrationStoreError, match=error):
        store.verify()


def test_dirty_and_unpushed_registration_are_rejected(registered):
    store, _provider, base, _result = registered
    head = commit_registration(store)
    unrelated = store.repo / "unrelated.txt"
    unrelated.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(registration.RegistrationStoreError, match="worktree_dirty"):
        store.verify_launch()
    unrelated.unlink()
    git(store.repo, "update-ref", "refs/remotes/origin/main", base)
    assert head != base
    with pytest.raises(registration.RegistrationStoreError, match="registration_not_pushed"):
        store.verify_launch()


def test_manifest_must_equal_git_head_bytes_even_if_status_is_hidden(registered):
    store, _provider, _base, _result = registered
    commit_registration(store)
    value = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    value["registered_utc"] = "2026-09-20T00:00:01+00:00"
    store.manifest_path.write_bytes(registration.canonical_bytes(value))
    git(store.repo, "update-index", "--assume-unchanged", store.manifest_name)
    with pytest.raises(registration.RegistrationStoreError, match="manifest_bytes_not_committed"):
        store.verify_launch()


def test_duplicate_historical_identity_is_rejected_before_manifest_creation(repository):
    store, _provider, _base = repository
    prior = json.loads((store.repo / "fixture/prior.json").read_text(encoding="utf-8"))
    prior["registration_id"] = store.expected_contract["registration_id"]
    (store.repo / "fixture/prior.json").write_text(json.dumps(prior, sort_keys=True) + "\n")
    git(store.repo, "add", "fixture/prior.json")
    git(
        store.repo, "-c", "user.name=Offline139", "-c",
        "user.email=offline139@example.invalid", "commit", "-qm", "duplicate identity fixture",
    )
    git(store.repo, "update-ref", "refs/remotes/origin/main", git(store.repo, "rev-parse", "HEAD"))
    with pytest.raises(registration.RegistrationStoreError, match="duplicate_registration_identity"):
        store.register()
    assert not store.manifest_path.exists()


def test_manifest_and_inventory_symlinks_are_rejected(registered):
    store, _provider, _base, _result = registered
    original = store.manifest_path.with_suffix(".original")
    store.manifest_path.rename(original)
    store.manifest_path.symlink_to(original.name)
    with pytest.raises(registration.RegistrationStoreError, match="registered_symlink_rejected"):
        store.verify()


def test_manifest_parent_symlink_is_rejected_without_writing_outside_repository(repository):
    store, provider, _base = repository
    outside = store.repo / "outside"
    outside.mkdir()
    link = store.repo / ".lunar" / "linked-fixture"
    link.parent.mkdir(mode=0o700)
    link.symlink_to("../" + outside.name, target_is_directory=True)
    linked_store = registration.RegistrationRepository(
        repo=store.repo,
        manifest_path=link / "manifest.json",
        expected_contract=store.expected_contract,
        measurement_names=("fixture/measurement.py",),
        historical_names=("fixture/history.json",),
        prior_manifest_names=("fixture/prior.json",),
        provider_probe=lambda: provider,
        runtime_probe=lambda: {"runtime": "offline-fixture"},
    )
    with pytest.raises(
        registration.RegistrationStoreError, match="parent_directory_symlink_or_invalid",
    ):
        linked_store.register()
    assert not (outside / "manifest.json").exists()


def test_inventory_symlink_is_rejected(registered):
    store, _provider, _base, _result = registered
    measurement = store.repo / "fixture/measurement.py"
    original = store.repo / "fixture/measurement-original.py"
    measurement.rename(original)
    measurement.symlink_to(original.name)
    with pytest.raises(registration.RegistrationStoreError, match="registered_symlink_rejected"):
        store.verify()


def test_one_slot_admission_is_atomic_and_cannot_be_reused(registered):
    store, _provider, _base, _result = registered
    head = commit_registration(store)
    marker = store.admit_one_slot()
    root = store.repo / store.expected_contract["campaign_root"]
    slot = root / store.expected_contract["attempt_id"]
    assert marker["registration_commit"] == head
    assert json.loads((root / "admission.json").read_text()) == marker
    assert json.loads((slot / "admission.json").read_text()) == marker
    with pytest.raises(registration.RegistrationStoreError, match="campaign_root_already_used"):
        store.admit_one_slot()


@pytest.mark.parametrize("existing", ("directory", "symlink"))
def test_existing_or_symlink_campaign_root_never_consumes_a_second_slot(registered, existing):
    store, _provider, _base, _result = registered
    commit_registration(store)
    root = store.repo / store.expected_contract["campaign_root"]
    root.parent.mkdir(mode=0o700)
    if existing == "directory":
        root.mkdir()
        (root / "attempt-001").mkdir()
    else:
        target = store.repo / "elsewhere"
        target.mkdir()
        os.symlink(target, root, target_is_directory=True)
    with pytest.raises(registration.RegistrationStoreError, match="campaign_root_already_used"):
        store.admit_one_slot()


def test_provider_metadata_cannot_contain_a_credential(repository):
    store, provider, _base = repository
    unsafe = copy.deepcopy(store.expected_contract)
    unsafe["provider_safe_metadata"] = {**provider, "api_key": "secret"}
    with pytest.raises(registration.RegistrationStoreError, match="unsafe_provider_metadata"):
        registration.RegistrationRepository(
            repo=store.repo,
            manifest_path=store.manifest_path,
            expected_contract=unsafe,
            measurement_names=("fixture/measurement.py",),
            historical_names=("fixture/history.json",),
            prior_manifest_names=("fixture/prior.json",),
            provider_probe=lambda: unsafe["provider_safe_metadata"],
            runtime_probe=lambda: {"runtime": "offline-fixture"},
        )
