"""Tampering tests for the separately implemented measurement registration auditor."""
import hashlib
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

AUDIT_PATH = Path(__file__).resolve().parents[1] / "specs/069-webagent-normal-workflow/measurement/audit.py"
SPEC = importlib.util.spec_from_file_location("measurement069_audit", AUDIT_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def schedule():
    return {
        "schema_version": "1", "campaign_id": audit.CAMPAIGN_ID,
        "planned_attempts": 4, "policy": dict(audit.POLICY),
        "execution": {"waves": [[1, 2], [3, 4]], "concurrency": 2,
                      "subject_outer_seconds": 5430, "harness_outer_seconds": 3630,
                      "slot_outer_seconds": 9300},
        "slots": [{"index": index, "arm": arm, "case_key": key,
                   "request_sha256": "a" * 64, "workflow_config": None}
                  for index, (arm, key) in enumerate(audit.ORDER, 1)],
        "outcomes": {"primary": "per-case exact-harness validity after accepted subject receipt",
                     "unscored_failure": None, "pooled_quality_mean": False,
                     "fixed_denominator_per_arm": 2, "retries_or_replacements": 0,
                     "historical_attempts_in_denominator": 0},
    }


@pytest.mark.parametrize("alteration", ["wave", "slot", "attempts", "retry", "policy", "null"])
def test_audit_rejects_changed_registered_protocol(alteration):
    manifest = schedule()
    audit.check_schedule(manifest)
    if alteration == "wave":
        manifest["execution"]["waves"] = [[1, 3], [2, 4]]
    elif alteration == "slot":
        manifest["slots"][1]["arm"] = "M"
    elif alteration == "attempts":
        manifest["planned_attempts"] = 5
    elif alteration == "retry":
        manifest["outcomes"]["retries_or_replacements"] = 1
    elif alteration == "policy":
        manifest["policy"]["checkpoint_after_rounds"] = 33
    else:
        manifest["outcomes"]["unscored_failure"] = 0
    with pytest.raises(audit.AuditError):
        audit.check_schedule(manifest)


def staged_binding():
    request = {"benchmark": {"name": "famou-bench"}, "public_files": [], "run_index": 1}
    request_sha = hashlib.sha256(audit.canonical(request, newline=True)).hexdigest()
    manifest = {"source_sha256": "a" * 64, "profile_sha256": audit.PROFILE_SHA}
    slot = {"index": 2, "arm": "S", "case_key": "china_post_pickup_optimization",
            "request_sha256": request_sha, "workflow_config": {
                "manifest": {"run_id": f"{audit.CAMPAIGN_ID}-slot-002",
                             "attempt_id": "slot-002-attempt-001", "source_sha256": "a" * 64,
                             "suite_key": "famou-bench", "case_key": "china_post_pickup_optimization",
                             "request_sha256": request_sha, "model_profile_sha256": audit.PROFILE_SHA,
                             "ceilings": dict(audit.CEILINGS)}, "policy": dict(audit.POLICY)}}
    return manifest, slot, request


@pytest.mark.parametrize("field,value", [
    ("run_id", "another-run"), ("attempt_id", "slot-003-attempt-001"),
    ("source_sha256", "b" * 64), ("request_sha256", "c" * 64),
    ("model_profile_sha256", "d" * 64), ("case_key", "sheet_metal_nesting"),
])
def test_audit_rejects_cross_attempt_or_identity_workflow(field, value):
    manifest, slot, request = staged_binding()
    audit.check_workflow(manifest, slot, request)
    slot["workflow_config"]["manifest"][field] = value
    with pytest.raises(audit.AuditError):
        audit.check_workflow(manifest, slot, request)


def test_audit_rejects_different_request_bytes_and_budget_extension():
    manifest, slot, request = staged_binding()
    changed_request = {**request, "run_index": 2}
    with pytest.raises(audit.AuditError, match="request digest"):
        audit.check_workflow(manifest, slot, changed_request)
    slot["workflow_config"]["manifest"]["ceilings"]["max_wall_seconds"] += 120
    with pytest.raises(audit.AuditError, match="shared budget"):
        audit.check_workflow(manifest, slot, request)


def test_audit_reads_actual_file_and_rejects_symlink_parent(tmp_path):
    directory = tmp_path / "evidence"
    directory.mkdir()
    path = directory / "proof.json"
    path.write_text("original")
    mapping = {"evidence/proof.json": audit.sha(path)}
    audit.check_map(tmp_path, mapping)
    path.write_text("modified")
    with pytest.raises(audit.AuditError, match="digest mismatch"):
        audit.check_map(tmp_path, mapping)
    link = tmp_path / "alias"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(audit.AuditError, match="linked evidence"):
        audit.check_map(tmp_path, {"alias/proof.json": audit.sha(path)})


def test_source_audit_rejects_missing_git_file_and_same_map_rehash(tmp_path, monkeypatch):
    source = tmp_path / "src/famou/module.py"
    source.parent.mkdir(parents=True)
    original = b"VALUE = 1\n"
    source.write_bytes(original)
    relative = "src/famou/module.py"
    manifest = {"implementation_commit": audit.IMPLEMENTATION,
                "source_files_sha256": {relative: audit.sha(source)}}
    manifest["source_sha256"] = audit.object_sha(manifest["source_files_sha256"])

    def pinned_git(command, **kwargs):
        assert command[0] == "git"
        return relative + "\n" if command[1] == "ls-tree" else original

    monkeypatch.setattr(audit.subprocess, "check_output", pinned_git)
    audit.check_source(tmp_path, manifest)
    untracked = source.with_name("untracked.py")
    untracked.write_text("unexpected")
    with pytest.raises(audit.AuditError, match="file set"):
        audit.check_source(tmp_path, manifest)
    untracked.unlink()
    altered = deepcopy(manifest)
    source.write_bytes(b"VALUE = 2\n")
    altered["source_files_sha256"][relative] = audit.sha(source)
    altered["source_sha256"] = audit.object_sha(altered["source_files_sha256"])
    with pytest.raises(audit.AuditError, match="pinned commit"):
        audit.check_source(tmp_path, altered)
