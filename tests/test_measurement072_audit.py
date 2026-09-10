"""Tampering tests for the separately implemented measurement registration auditor."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

AUDIT_PATH = Path(__file__).resolve().parents[1] / "specs/072-master-budget-measurement/measurement/audit.py"
SPEC = importlib.util.spec_from_file_location("measurement072_audit", AUDIT_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"measurement072_test_{name}", AUDIT_PATH.with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schedule():
    return {
        "schema_version": "1", "campaign_id": audit.CAMPAIGN_ID,
        "planned_attempts": 4, "policies": deepcopy(audit.POLICIES),
        "execution": {"waves": [[1, 2], [3, 4]], "concurrency": 2,
                      "subject_outer_seconds": 5430, "harness_outer_seconds": 3630,
                      "slot_outer_seconds": 9300},
        "slots": [{"index": index, "arm": "S", "budget_arm": budget_arm, "case_key": key,
                   "request_sha256": "a" * 64, "workflow_config": None}
                  for index, (budget_arm, key) in enumerate(audit.ORDER, 1)],
        "outcomes": {"primary": "per-case exact-harness validity after accepted subject receipt",
                     "unscored_failure": None, "pooled_quality_mean": False,
                     "fixed_denominator_per_budget_arm": 2, "retries_or_replacements": 0,
                     "historical_attempts_in_denominator": 0,
                     "secondary": "validated Master plan handoff and observed Build evidence",
                     "master_duration_seconds": None},
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
        manifest["policies"]["master_300"]["checkpoint_after_rounds"] = 33
    else:
        manifest["outcomes"]["unscored_failure"] = 0
    with pytest.raises(audit.AuditError):
        audit.check_schedule(manifest)


def staged_binding():
    request = {"benchmark": {"name": "famou-bench"}, "public_files": [], "run_index": 1}
    request_sha = hashlib.sha256(audit.canonical(request, newline=True)).hexdigest()
    manifest = {"source_sha256": "a" * 64, "profile_sha256": audit.PROFILE_SHA}
    slot = {"index": 2, "arm": "S", "budget_arm": "master_1200", "case_key": "china_post_pickup_optimization",
            "request_sha256": request_sha, "workflow_config": {
                "manifest": {"run_id": f"{audit.CAMPAIGN_ID}-slot-002",
                             "attempt_id": "slot-002-attempt-001", "source_sha256": "a" * 64,
                             "suite_key": "famou-bench", "case_key": "china_post_pickup_optimization",
                             "request_sha256": request_sha, "model_profile_sha256": audit.PROFILE_SHA,
                             "ceilings": dict(audit.CEILINGS)}, "policy": dict(audit.POLICIES["master_1200"])}}
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


@pytest.mark.parametrize("change", ["swapped_group", "changed_limit", "shared_policy", "normal_arm", "duration"])
def test_budget_groups_cannot_hide_treatment_or_timing_changes(change):
    manifest = schedule()
    if change == "swapped_group":
        manifest["slots"][0]["budget_arm"] = "master_1200"
    elif change == "changed_limit":
        manifest["policies"]["master_1200"]["master_seconds"] = 1800
    elif change == "shared_policy":
        manifest["policies"]["master_1200"] = dict(manifest["policies"]["master_300"])
    elif change == "normal_arm":
        manifest["slots"][0]["arm"] = "M"
    else:
        manifest["outcomes"]["master_duration_seconds"] = 300
    with pytest.raises(audit.AuditError):
        audit.check_schedule(manifest)


def test_workflow_budget_group_must_match_registered_policy():
    manifest, slot, request = staged_binding()
    slot["workflow_config"]["policy"] = dict(audit.POLICIES["master_300"])
    with pytest.raises(audit.AuditError, match="shared budget"):
        audit.check_workflow(manifest, slot, request)


@pytest.mark.parametrize("name", ["started.json", "terminated.json", "summary.json", "slots",
                                 "slot-001-started.json", "slot-004-terminated.json", "slot-005-started.json"])
def test_unstarted_audit_rejects_orphaned_control_markers(tmp_path, name):
    audit.check_unstarted(tmp_path)
    (tmp_path / name).write_text("{}")
    with pytest.raises(audit.AuditError, match="unstarted"):
        audit.check_unstarted(tmp_path)


def test_frozen_dependency_map_covers_helpers_reporters_and_tests(tmp_path, monkeypatch):
    here = tmp_path / "specs/072-master-budget-measurement/measurement"
    campaign = tmp_path / ".lunar" / audit.CAMPAIGN_ID
    relative_files = [
        *(f"specs/072-master-budget-measurement/measurement/{name}.py"
          for name in ("prepare", "audit", "dry_run", "adapter", "worker", "campaign")),
        *(f"specs/072-master-budget-measurement/postrun/{name}.py"
          for name in ("audit", "render_report", "test_audit")),
        *(f"{audit.LEGACY_ROOT}/measurement/{name}.py"
          for name in ("prepare", "worker", "campaign", "audit", "dry_run")),
        f"{audit.LEGACY_ROOT}/postrun/audit.py", f"{audit.LEGACY_ROOT}/postrun/render_report.py",
        "tests/test_fixture.py", ".lunar/real-eval-20260908/ccswitch.py", ".venv/bin/lunar-agent",
        ".lunar/harness-venv-high-score-20260909/bin/python",
        f".lunar/{audit.CAMPAIGN_ID}/inputs/profile.json", f".lunar/{audit.CAMPAIGN_ID}/readiness.json",
    ]
    for relative in relative_files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frozen\n")
    mapping = {relative: audit.sha(tmp_path / relative) for relative in relative_files}
    manifest = {"frozen_files_sha256": mapping}
    monkeypatch.setattr(audit.subprocess, "check_output", lambda *_a, **_k: b"frozen\n")
    audit.check_frozen(tmp_path, campaign, manifest, here)
    missing = deepcopy(manifest)
    del missing["frozen_files_sha256"][f"{audit.LEGACY_ROOT}/measurement/worker.py"]
    with pytest.raises(audit.AuditError, match="incomplete executable"):
        audit.check_frozen(tmp_path, campaign, missing, here)
    relative = f"{audit.LEGACY_ROOT}/postrun/audit.py"
    (tmp_path / relative).write_bytes(b"rehashed alteration\n")
    mapping[relative] = audit.sha(tmp_path / relative)
    with pytest.raises(audit.AuditError, match="pinned commit"):
        audit.check_frozen(tmp_path, campaign, manifest, here)


def test_sealed_history_rejects_rehashed_edits_or_incomplete_seal(tmp_path, monkeypatch):
    root = tmp_path / audit.LEGACY_ROOT
    data = {
        "measurement/manifest.json": {"historical_files_sha256": {"prior.json": ""}},
        "postrun/final-audit.json": {"passed": True, "complete": True, "final_acceptance": True},
    }
    (tmp_path / "prior.json").write_text("historical context")
    data["measurement/manifest.json"]["historical_files_sha256"]["prior.json"] = audit.sha(tmp_path / "prior.json")
    for relative, payload in data.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    data["postrun/final-audit.json"]["manifest_sha256"] = audit.sha(root / "measurement/manifest.json")
    (root / "postrun/final-audit.json").write_text(json.dumps(data["postrun/final-audit.json"]))
    pins = {f"{audit.LEGACY_ROOT}/{relative}": audit.sha(root / relative) for relative in data}
    monkeypatch.setattr(audit, "SEALED_HISTORY", pins)
    manifest = {"historical_files_sha256": {
        **data["measurement/manifest.json"]["historical_files_sha256"], **pins,
    }}
    audit.check_history(tmp_path, manifest)
    (tmp_path / "prior.json").write_text("changed historical score")
    manifest["historical_files_sha256"]["prior.json"] = audit.sha(tmp_path / "prior.json")
    with pytest.raises(audit.AuditError, match="sealed context"):
        audit.check_history(tmp_path, manifest)


@pytest.mark.parametrize("seconds", [300, 1200])
def test_native_master_timeout_is_terminal_under_both_registered_limits(tmp_path, seconds):
    from test_staged_effect_adapter import _config, _profile, _request

    from famou.agent_loop import AgentLoopRuntime
    from famou.staged_workflow import StagedWorkflowConfig, StagedWorkflowRunner, StagePolicy
    from famou.workflow_checkpoint import WorkflowCheckpointError, WorkflowController

    profile = replace(_profile(), model="glm-5.2", timeout_seconds=5400, max_steps=200,
                      max_total_tokens=8_000_000)
    request = _request(tmp_path / "subject", profile)
    old_config = _config(request, profile)
    config = StagedWorkflowConfig(replace(old_config.manifest, ceilings=dict(audit.CEILINGS)),
                                  StagePolicy(seconds, 2400, 120, 32))

    class TimedOut:
        def __init__(self):
            self.timeouts = []

        def complete(self, messages, tools=(), timeout=None):
            self.timeouts.append(timeout)
            raise TimeoutError("deterministic offline Master timeout")

    model = TimedOut()
    controller = WorkflowController(request.parent, config.manifest)
    runner = StagedWorkflowRunner(controller, AgentLoopRuntime(model, profile=profile, max_steps=200),
                                 request.parent, policy=config.policy)
    with pytest.raises(TimeoutError):
        runner.run("public offline fixture")
    assert len(model.timeouts) == 1 and seconds - 1 < model.timeouts[0] <= seconds
    assert controller.state()["stage"] == "master_running"
    assert not runner.usage_ledger.usage_complete
    assert not (request.parent / "workflow/session-transcript.jsonl").exists()
    assert not (request.parent / "receipt.json").exists()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert len(model.timeouts) == 1


@pytest.mark.parametrize("kind", ["skipped", "failure", "error", "missing", "duplicate"])
def test_offline_report_rejects_nonpassing_or_incomplete_test_evidence(tmp_path, monkeypatch, kind):
    dry = load_script("dry_run")
    monkeypatch.setattr(dry, "NODES", ("tests/example.py::test_one",))
    body = '<testcase classname="example" name="test_one">'
    body += f"<{kind}/>" if kind in {"skipped", "failure", "error"} else ""
    body += "</testcase>"
    body = "" if kind == "missing" else body * 2 if kind == "duplicate" else body
    path = tmp_path / "results.xml"
    path.write_text("<testsuite>" + body + "</testsuite>")
    with pytest.raises(dry.DryRunError):
        dry.parse_results(path)


def test_offline_checks_require_frozen_test_bytes():
    dry = load_script("dry_run")
    pins = {"tests/fixture.py": "a" * 64}
    dry.verify_test_pins({"frozen_files_sha256": pins}, pins)
    with pytest.raises(dry.DryRunError):
        dry.verify_test_pins({"frozen_files_sha256": {}}, pins)


def case_fixture(tmp_path, monkeypatch):
    """A tiny independent public/private tree; private scripts are hashed, never run."""
    key = "fixture_case"
    relative = f".lunar/high-score-case-selection-20260909/kit-build/{key}"
    kit = tmp_path / relative
    for surface in ("public", "private"):
        root = kit / surface
        (root / "data").mkdir(parents=True)
        (root / "instruction.md").write_text("Return the fixture value.\n")
        (root / "data/input.json").write_text('{"value":42}\n')
    (kit / "private/tests").mkdir()
    for name in ("extractor_agent.py", "evaluator.py"):
        (kit / "private/tests" / name).write_text("raise RuntimeError('private fixture must never execute')\n")
    private_digest = audit.famou_case_content_digest(kit / "private")
    extractor_sha = audit.sha(kit / "private/tests/extractor_agent.py")
    evaluator_sha = audit.sha(kit / "private/tests/evaluator.py")
    case = {
        "key": key, "revision_id": "fixture-revision", "digest": private_digest,
        "entrypoint": "instruction.md", "public_files": [
            {"path": relative, "size": (kit / "public" / relative).stat().st_size,
             "sha256": audit.sha(kit / "public" / relative)}
            for relative in ("instruction.md", "data/input.json")
        ], "harness": {"extractor_sha256": extractor_sha, "evaluator_sha256": evaluator_sha},
    }
    suite = {
        "schema_version": "1", "benchmark": {
            "name": "famou-bench", "release_version": "1.10.6", "publication_digest": "sha256:" + "a" * 64,
        }, "evaluation_profile": {"name": "fixture-profile", "revision": 1, "digest": "sha256:" + "b" * 64},
        "cases": [case],
    }
    (kit / "suite.json").write_text(json.dumps(suite))
    campaign = tmp_path / ".lunar" / audit.CAMPAIGN_ID
    (campaign / "inputs").mkdir(parents=True)
    (campaign / "inputs" / f"{key}-suite.json").write_text(json.dumps(suite))
    selection = {"experiment_id": "offline-selection", "model": "glm-5.2", "agent_family": "AgentServer/OpenCode",
                 "by_case": {key: {"runs": [
                     {"run_index": index, "evaluation_status": "scored", "extraction_status": "extracted",
                      "conclusion_eligibility": "eligible", "validity_score": 1, "overall_score": 0.75}
                     for index in range(3)
                 ]}}}
    selection_path = kit.parent.parent / "baseline-audit.json"
    selection_path.write_text(json.dumps(selection))
    prepare = load_script("prepare")
    baseline = prepare.baseline_projection(audit.TrialSuite.from_dict(suite), selection)
    (campaign / "inputs" / f"{key}-baseline.json").write_text(json.dumps(baseline))
    monkeypatch.setattr(audit, "CASE_PINS", {key: {
        "digest": private_digest, "revision_id": case["revision_id"], "evaluator_sha256": evaluator_sha,
    }})
    monkeypatch.setattr(audit, "EXTRACTOR_SHA", extractor_sha)
    manifest = {"cases": {key: {"suite": suite, "public_root_rel": relative + "/public",
                               "private_root_rel": relative + "/private"}},
                "source_sha256": "c" * 64, "profile_sha256": audit.PROFILE_SHA,
                "selection_evidence": {
                    "experiment_id": selection["experiment_id"], "source": "Platform WebAgent/AgentServer (OpenCode)",
                    "baseline_audit_sha256": audit.sha(selection_path),
                }, "slots": []}
    request = audit.request_for(audit.TrialSuite.from_dict(suite), audit.PROFILE_SHA)
    request_sha = hashlib.sha256(audit.canonical(request, newline=True)).hexdigest()
    for index, group in enumerate(("master_300", "master_1200"), 1):
        workflow = {"manifest": {
            "run_id": f"{audit.CAMPAIGN_ID}-slot-{index:03d}", "attempt_id": f"slot-{index:03d}-attempt-001",
            "source_sha256": manifest["source_sha256"], "suite_key": "famou-bench", "case_key": key,
            "request_sha256": request_sha, "model_profile_sha256": audit.PROFILE_SHA,
            "ceilings": dict(audit.CEILINGS),
        }, "policy": dict(audit.POLICIES[group])}
        manifest["slots"].append({"index": index, "arm": "S", "budget_arm": group, "case_key": key,
                                  "request_sha256": request_sha, "workflow_config": workflow})
        (campaign / "inputs" / f"slot-{index:03d}-workflow.json").write_text(json.dumps(workflow))
    old = {"slots": [{"case_key": key, "case_digest": private_digest, "harness": case["harness"],
                      "suite_sha256": audit.sha(kit / "suite.json")} ]}
    return kit, campaign, manifest, old


@pytest.mark.parametrize("change", ["private", "extractor", "evaluator", "public", "extra_public", "workflow"])
def test_independent_case_check_reads_native_input_and_harness_bytes(tmp_path, monkeypatch, change):
    kit, campaign, manifest, old = case_fixture(tmp_path, monkeypatch)
    audit.check_cases(tmp_path, campaign, manifest, old)
    targets = {
        "private": kit / "private/data/input.json",
        "extractor": kit / "private/tests/extractor_agent.py",
        "evaluator": kit / "private/tests/evaluator.py",
        "public": kit / "public/data/input.json",
        "extra_public": kit / "public/extra.txt",
        "workflow": campaign / "inputs/slot-002-workflow.json",
    }
    targets[change].write_text('{}\n')
    with pytest.raises(audit.AuditError):
        audit.check_cases(tmp_path, campaign, manifest, old)
