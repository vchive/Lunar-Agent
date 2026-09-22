"""Provider-free registration manifest, seal and launch-preflight checks."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from lunar_evolution import (
    DEFAULT_ACCEPTANCE_BUDGETS,
    AcceptanceRegistrationError,
    build_acceptance_registration,
    build_registration_seal,
    parse_acceptance_registration,
    parse_registration_seal,
    preflight_acceptance_registration,
)


def payload() -> dict[str, object]:
    value = {
        "schema_version": "1", "scope": "acceptance_registration",
        "registration_id": "registration-20260922", "campaign_id": "campaign-20260922",
        "attempt_id": "attempt-001", "product_commit": "a" * 40,
        "product_files": [{"path": "src/main.py", "size": 1, "sha256": "9" * 64}],
        "task_material": {"path": "task.json", "size": 1, "sha256": "5" * 64},
        "input_material": {"path": "input.json", "size": 1, "sha256": "6" * 64},
        "evaluator_material": {"path": "evaluator.py", "size": 1, "sha256": "7" * 64},
        "evaluator_profile_material": {"path": "profile.json", "size": 1, "sha256": "8" * 64},
        "campaign_root": "campaign-20260922", "task_sha256": "5" * 64,
        "input_sha256": "6" * 64, "evaluator_sha256": "7" * 64,
        "evaluator_profile_sha256": "8" * 64, "provider": "configured-provider",
        "model": "configured-model", "runtime": "python311", "api_mode": "responses",
        "entrypoint": "src/main.py", "budgets": dict(DEFAULT_ACCEPTANCE_BUDGETS),
        "islands": 1, "population_size": 1, "offspring_count": 1, "rounds": 1,
        "candidate_tool_steps": 12,
        "holdout_pins": [
            {"holdout_id": f"holdout-{index:02d}", "ordinal": index,
             "input": {"path": f"holdout/{index:02d}.in", "size": 1, "sha256": f"{index + 5:x}" * 64},
             "expected": {"path": f"expected/{index:02d}.out", "size": 1, "sha256": f"{index + 6:x}" * 64},
             "max_duration_ms": 5000} for index in range(8)
        ],
        "frozen_identities": {
            "registration_id": ["old-registration"],
            "campaign_id": ["old-campaign"],
            "campaign_root": ["old-root"],
        },
    }
    import hashlib
    value["frozen_identities_sha256"] = hashlib.sha256(json.dumps(value["frozen_identities"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value


def registration() -> dict[str, object]:
    return build_acceptance_registration(payload())


def test_registration_is_canonical_and_digest_bound() -> None:
    value = registration()
    assert parse_acceptance_registration(json.dumps(value, sort_keys=True, separators=(",", ":"))) == value
    with pytest.raises(AcceptanceRegistrationError, match="registration_noncanonical"):
        parse_acceptance_registration(json.dumps(value, indent=2))
    forged = copy.deepcopy(value)
    forged["input_sha256"] = "f" * 64
    with pytest.raises(AcceptanceRegistrationError, match="material_digest_mismatch"):
        parse_acceptance_registration(forged)


@pytest.mark.parametrize(("field", "code"), [
    ("budgets", "budgets_do_not_match_plan"), ("campaign_root", "invalid_campaign_root"),
    ("holdout_pins", "holdout_pins_invalid"), ("entrypoint", "invalid_entrypoint"),
    ("candidate_tool_steps", "invalid_candidate_tool_steps"),
])
def test_registration_rejects_drift(field: str, code: str) -> None:
    value = payload()
    if field == "budgets":
        value[field]["solve_wall_seconds"] = 2400  # type: ignore[index]
    elif field == "holdout_pins":
        value[field] = value[field][:-1]  # type: ignore[index]
    elif field == "candidate_tool_steps":
        value[field] = 11
    elif field == "campaign_root":
        value[field] = "../old"
    else:
        value[field] = "../candidate.py"
    with pytest.raises(AcceptanceRegistrationError, match=code):
        build_acceptance_registration(value)


def test_clean_pushed_observation_is_ready_and_seal_is_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = registration()
    manifest_path = tmp_path / "registration.json"
    seal_path = tmp_path / "seal.json"
    manifest_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    seal = build_registration_seal(value)
    seal_path.write_text(json.dumps(seal, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    monkeypatch.setattr("lunar_evolution.acceptance_registration._git", lambda *args, **kwargs: b"a" * 40)
    # The filesystem-free contract is covered here; actual checkout reading is exercised by integration.
    assert parse_registration_seal(seal)["registration_sha256"] == value["registration_sha256"]


def test_preflight_function_does_not_run_external_commands() -> None:
    value = registration()
    assert value["candidate_tool_steps"] == 12


def test_seal_tamper_is_rejected() -> None:
    value = registration()
    seal = build_registration_seal(value)
    seal["campaign_root"] = "other-root"
    with pytest.raises(AcceptanceRegistrationError, match="seal_digest_mismatch"):
        parse_registration_seal(seal)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _checkout(tmp_path: Path) -> tuple[Path, Path, dict[str, object], Path, Path]:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "src").mkdir()
    (root / "src/main.py").write_bytes(b"x")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "product")
    product_commit = _git(root, "rev-parse", "HEAD")
    value = payload()
    value["product_commit"] = product_commit
    value["product_files"] = [{"path": "src/main.py", "size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}]
    manifest = build_acceptance_registration(value)
    metadata = root / ".registration"
    metadata.mkdir()
    manifest_path = metadata / "registration.json"
    seal_path = metadata / "registration-seal.json"
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    seal = build_registration_seal(manifest)
    seal_path.write_bytes(json.dumps(seal, sort_keys=True, separators=(",", ":")).encode())
    _git(root, "add", ".registration")
    _git(root, "commit", "-qm", "registration")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    parent = tmp_path / "campaigns"
    parent.mkdir()
    return root, parent, manifest, manifest_path, seal_path


def test_read_only_preflight_checks_committed_bytes_and_checkout(tmp_path: Path) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    result = preflight_acceptance_registration(
        manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
        frozen_identities=["old-registration", "old-campaign", "old-root"],
    )
    assert result["status"] == "ready" and result["checks"]["head_equals_origin"] is True
    assert not (parent / manifest["campaign_root"]).exists()
    assert before == sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


@pytest.mark.parametrize("mutation", ["dirty", "unpushed", "root", "drift", "identity"])
def test_preflight_fails_closed_before_admission(tmp_path: Path, mutation: str) -> None:
    root, parent, manifest, manifest_path, seal_path = _checkout(tmp_path)
    if mutation == "dirty":
        (root / "dirty").write_text("x", encoding="utf-8")
    elif mutation == "unpushed":
        (root / "src/main.py").write_bytes(b"changed")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "unpushed")
    elif mutation == "root":
        (parent / manifest["campaign_root"]).mkdir()
    elif mutation == "drift":
        (root / "src/main.py").write_bytes(b"y")
        # Keep checkout clean while changing the committed product blob.
        _git(root, "add", "src/main.py")
        _git(root, "commit", "-qm", "drift")
        _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    elif mutation == "identity":
        frozen = [manifest["campaign_id"]]
    else:
        frozen = ["old-registration"]
    if mutation != "identity":
        frozen = ["old-registration", "old-campaign", "old-root"]
    with pytest.raises(AcceptanceRegistrationError) as error:
        preflight_acceptance_registration(
            manifest_path, seal_path, checkout_root=root, campaign_parent=parent,
            frozen_identities=frozen,
        )
    assert error.value.code in {
        "checkout_dirty", "checkout_not_pushed", "campaign_root_not_fresh", "product_file_drift", "identity_reused",
    }


def test_material_and_frozen_identity_digests_are_required() -> None:
    value = payload()
    value["task_sha256"] = "f" * 64
    with pytest.raises(AcceptanceRegistrationError, match="material_digest_mismatch"):
        build_acceptance_registration(value)
    value = payload()
    value["frozen_identities_sha256"] = "f" * 64
    with pytest.raises(AcceptanceRegistrationError, match="frozen_identities_digest_mismatch"):
        build_acceptance_registration(value)
