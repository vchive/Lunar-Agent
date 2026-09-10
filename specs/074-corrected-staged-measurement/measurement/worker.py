"""Two staged subjects reuse the native worker with exact per-budget registration checks."""
from __future__ import annotations

import os
from pathlib import Path

from adapter import EXECUTION, ORDER, POLICIES, REPO, load_legacy

from famou.effect_adapters import famou_case_content_digest
from famou.effect_trial import TrialBaseline, TrialSuite, _profile_digest
from famou.profiles import ModelProfile
from famou.staged_workflow import StagedWorkflowConfig, StagePolicy

native = load_legacy("worker")
HARNESS_PYTHON = native.HARNESS_PYTHON
SUBJECT_ENV_NAMES, HARNESS_ENV_NAMES = native.SUBJECT_ENV_NAMES, native.HARNESS_ENV_NAMES
require, confined, read_json = native.require, native.confined, native.read_json
file_sha256, canonical_sha256 = native.file_sha256, native.canonical_sha256
input_path, load_registration = native.input_path, native.load_registration
request_sha256, write_new = native.request_sha256, native.write_new
commands, build_runner = native.commands, native.build_runner
split_environment, RegisteredExecutor = native.split_environment, native.RegisteredExecutor


def select_slot(manifest, index):
    require(type(index) is int and index in (1, 2))
    slots = manifest["slots"]
    require(isinstance(slots, list) and len(slots) == 2)
    for number, (slot, (budget_arm, key)) in enumerate(zip(slots, ORDER, strict=True), 1):
        require(set(slot) == {"index", "arm", "budget_arm", "case_key", "request_sha256", "workflow_config"})
        require(type(slot["index"]) is int and slot["index"] == number and slot["arm"] == "S")
        require(slot["budget_arm"] == budget_arm and slot["case_key"] == key)
    return slots[index - 1]


def verify_bindings(manifest_path, campaign, manifest, manifest_sha, slot, *, require_started=True):
    """Retain every native worker binding check; validate this slot against its actual policy."""
    loaded, actual_manifest_sha = load_registration(manifest_path)
    require(loaded == manifest and actual_manifest_sha == manifest_sha)
    require(campaign.name == manifest["campaign_id"])
    require(confined(REPO, campaign.relative_to(REPO).as_posix()) == campaign)
    require(select_slot(manifest, slot["index"]) == slot)
    require(manifest["planned_attempts"] == 2 and manifest["execution"] == EXECUTION)
    require(manifest["policies"] == POLICIES)
    sources = manifest["source_files_sha256"]
    require(isinstance(sources, dict) and bool(sources))
    actual_sources = {
        path.relative_to(REPO).as_posix(): file_sha256(confined(REPO, path.relative_to(REPO).as_posix()))
        for path in sorted((REPO / "src/famou").rglob("*.py"))
    }
    require(actual_sources == sources and canonical_sha256(sources) == manifest["source_sha256"])
    for relative, expected in manifest["frozen_files_sha256"].items():
        require(file_sha256(confined(REPO, relative)) == expected)
    for path in (Path(__file__), Path(native.__file__)):
        require(path.relative_to(REPO).as_posix() in manifest["frozen_files_sha256"])
    require(HARNESS_PYTHON in manifest["frozen_files_sha256"])
    case_key = slot["case_key"]
    case_info = manifest["cases"][case_key]
    suite = read_json(input_path(campaign, case_key + "-suite.json"))
    require(suite == case_info["suite"])
    parsed = TrialSuite.from_dict(suite)
    require(len(parsed.cases) == 1 and parsed.cases[0].key == case_key)
    profile = ModelProfile.from_dict(read_json(input_path(campaign, "profile.json")))
    require(profile.to_dict() == manifest["profile"])
    require(_profile_digest(profile) == manifest["profile_sha256"])
    require(profile.model == "glm-5.2" and profile.max_steps == 200)
    require(profile.timeout_seconds == 5400 and profile.max_total_tokens == 8000000)
    require(profile.thinking_budget == 0 and profile.max_cost_micros is None)
    require(profile.input_cost_per_1k_micros is None and profile.output_cost_per_1k_micros is None)
    require(slot["request_sha256"] == request_sha256(suite, manifest["profile_sha256"]))
    baseline = TrialBaseline.from_dict(read_json(input_path(campaign, case_key + "-baseline.json")))
    require(baseline.source == "company-platform" and baseline.conclusion_eligibility == "ineligible")
    require(baseline.provenance is not None and baseline.provenance.adapter == "agentserver")
    private = confined(REPO, case_info["private_root_rel"])
    require(famou_case_content_digest(private) == parsed.cases[0].digest)
    for name, expected in (("extractor_agent.py", parsed.cases[0].harness.extractor_sha256),
                           ("evaluator.py", parsed.cases[0].harness.evaluator_sha256)):
        require(file_sha256(confined(private, "tests/" + name)) == expected)
    policy = StagePolicy.from_dict(manifest["policies"][slot["budget_arm"]])
    name = f"slot-{slot['index']:03d}-workflow.json"
    workflow = StagedWorkflowConfig.load(input_path(campaign, name))
    require(workflow.to_dict() == slot["workflow_config"] and workflow.policy == policy)
    control = workflow.manifest
    require(control.run_id == f"{manifest['campaign_id']}-slot-{slot['index']:03d}")
    require(control.attempt_id == f"slot-{slot['index']:03d}-attempt-001")
    require(control.source_sha256 == manifest["source_sha256"])
    require(control.request_sha256 == slot["request_sha256"])
    require(control.model_profile_sha256 == manifest["profile_sha256"])
    require(control.suite_key == parsed.benchmark.name and control.case_key == case_key)
    require(dict(control.ceilings) == {"max_wall_seconds": 5400, "max_tool_steps": 200,
                                       "max_total_tokens": 8000000, "max_cost_micros": None})
    required_inputs = ["profile.json", case_key + "-suite.json", case_key + "-baseline.json", name]
    for name in required_inputs:
        require(input_path(campaign, name).relative_to(REPO).as_posix() in manifest["frozen_files_sha256"])
    if require_started:
        for name in ("started.json", f"slot-{slot['index']:03d}-started.json"):
            marker = read_json(confined(campaign, name))
            require(marker["manifest_sha256"] == manifest_sha)
            if name != "started.json":
                require(marker["index"] == slot["index"])
        require(not os.path.lexists(campaign / "terminated.json"))
        require(not os.path.lexists(campaign / f"slot-{slot['index']:03d}-terminated.json"))


# Only this private instance is configured. Its execution, receipt gate, process markers and
# cleanup functions are the original frozen functions; no old file or global import is changed.
native.select_slot = select_slot
native.verify_bindings = verify_bindings
main = native.main


if __name__ == "__main__":
    import json
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - bounded output never prints provider-bearing details
        print(json.dumps({"status": "worker_rejected", "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(2) from None
