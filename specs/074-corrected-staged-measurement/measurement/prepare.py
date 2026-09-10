"""Materialize two fresh staged inputs; importing this module is offline and read-only."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from adapter import (
    CAMPAIGN,
    CAMPAIGN_ID,
    EXECUTION,
    HELPER_FILES,
    HERE,
    IMPLEMENTATION,
    ORDER,
    POLICIES,
    REPO,
    load_prior,
)
from audit import OUTCOMES, PRIOR_ROOT, check_source, code_paths, frozen_paths, historical_map

from famou.effect_adapters import famou_case_content_digest
from famou.effect_trial import TrialSuite, _canonical_bytes, _profile_digest
from famou.profiles import ModelProfile
from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import WorkflowManifest

native = load_prior("prepare")
sha, object_sha, read, write_new, require = native.sha, native.object_sha, native.read, native.write_new, native.require
expected_request, baseline_projection = native.expected_request, native.baseline_projection
OLD = REPO / ".lunar/real-eval-glm-5.2-high-score-20260909"
HARNESS_PYTHON = REPO / ".lunar/harness-venv-high-score-20260909/bin/python"


def workflow_for(index, key, suite, profile_sha, source_sha, request_sha):
    return StagedWorkflowConfig(WorkflowManifest(
        run_id=f"{CAMPAIGN_ID}-slot-{index:03d}", attempt_id=f"slot-{index:03d}-attempt-001",
        source_sha256=source_sha, suite_key=suite.benchmark.name, case_key=key,
        request_sha256=request_sha, model_profile_sha256=profile_sha,
        ceilings={"max_wall_seconds": 5400, "max_tool_steps": 200,
                  "max_total_tokens": 8_000_000, "max_cost_micros": None},
    ), StagePolicy.from_dict(POLICIES["master_1200"])).to_dict()


def main():
    require(not os.path.lexists(CAMPAIGN) and not os.path.lexists(HERE / "manifest.json"), "registration already exists")
    import famou
    require(Path(famou.__file__).resolve().parent == REPO / "src/famou", "wrong imported product source")
    source = {path.relative_to(REPO).as_posix(): sha(path) for path in sorted((REPO / "src/famou").rglob("*.py"))}
    source_sha = object_sha(source)
    check_source(REPO, {"implementation_commit": IMPLEMENTATION,
                        "source_files_sha256": source, "source_sha256": source_sha})
    code_paths(REPO, HERE)
    require(all(sha(REPO / path) == digest for path, digest in HELPER_FILES.items()), "pinned helper changed")
    history = historical_map(REPO)
    prior = read(REPO / PRIOR_ROOT / "measurement/manifest.json")
    profile = ModelProfile.from_dict(prior["profile"])
    profile_sha = _profile_digest(profile)
    require(profile_sha == prior["profile_sha256"] and profile.model == "glm-5.2"
            and profile.max_steps == 200 and profile.timeout_seconds == 5400 and profile.max_total_tokens == 8_000_000)
    loader_relative = ".lunar/real-eval-20260908/ccswitch.py"
    require(sha(REPO / loader_relative) == prior["frozen_files_sha256"][loader_relative],
            "authorized configuration loader changed")
    endpoints = native.local_provider_snapshot()  # Authorized local configuration only; no provider request.
    require(endpoints == prior["endpoints"], "authorized endpoint identity changed")
    old = read(OLD / "manifest.json")
    require(sha(HARNESS_PYTHON) == old["harness_python_sha256"], "harness launcher changed")
    probe = '''import json, platform
from importlib.metadata import distributions
import anyio, pandas, numpy
from claude_agent_sdk import query, ClaudeAgentOptions
print(json.dumps({"python_version":platform.python_version(),"packages":{
 d.metadata["Name"].lower().replace("_","-"):d.version for d in distributions()}}))
'''
    readiness = json.loads(subprocess.check_output(
        [str(HARNESS_PYTHON), "-c", probe], text=True, timeout=30,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    ))
    old_readiness = read(OLD / "readiness.json")
    require(all(readiness[name] == old_readiness[name] for name in ("packages", "python_version")),
            "harness dependency identity changed")
    readiness.update(model_calls=0, provider_configuration_complete=True, endpoint_identities_unchanged=True,
                     harness_python_sha256=sha(HARNESS_PYTHON))
    selection_path = REPO / ".lunar/high-score-case-selection-20260909/baseline-audit.json"
    selection = read(selection_path)
    inputs = CAMPAIGN / "inputs"
    inputs.mkdir(parents=True)
    write_new(inputs / "profile.json", profile.to_dict())
    write_new(CAMPAIGN / "readiness.json", readiness)
    cases, slots = {}, []
    for index, (group, key) in enumerate(ORDER, 1):
        info = prior["cases"][key]
        suite = TrialSuite.from_dict(info["suite"])
        require(len(suite.cases) == 1 and suite.cases[0].key == key)
        case = suite.cases[0]
        private, public = REPO / info["private_root_rel"], REPO / info["public_root_rel"]
        require(famou_case_content_digest(private) == case.digest, "actual private case changed")
        for name, digest in (("extractor_agent.py", case.harness.extractor_sha256),
                             ("evaluator.py", case.harness.evaluator_sha256)):
            require(sha(private / "tests" / name) == digest, "exact harness changed")
        for item in case.public_files:
            require(sha(public / item.path) == item.sha256 and (public / item.path).stat().st_size == item.size)
        write_new(inputs / f"{key}-suite.json", suite.to_dict())
        write_new(inputs / f"{key}-baseline.json", baseline_projection(suite, selection))
        cases[key] = info
        request_sha = hashlib.sha256(_canonical_bytes(expected_request(suite, profile_sha))).hexdigest()
        workflow = workflow_for(index, key, suite, profile_sha, source_sha, request_sha)
        write_new(inputs / f"slot-{index:03d}-workflow.json", workflow)
        slots.append({"index": index, "arm": "S", "budget_arm": group, "case_key": key,
                      "request_sha256": request_sha, "workflow_config": workflow})
    frozen = {relative: sha(REPO / relative) for relative in sorted(frozen_paths(REPO, CAMPAIGN, HERE))}
    manifest = {
        "schema_version": "1", "campaign_id": CAMPAIGN_ID, "registered_utc": datetime.now(UTC).isoformat(),
        "implementation_commit": IMPLEMENTATION, "source_files_sha256": source, "source_sha256": source_sha,
        "profile": profile.to_dict(), "profile_sha256": profile_sha, "policies": POLICIES,
        "execution": EXECUTION, "planned_attempts": 2, "cases": cases, "slots": slots, "endpoints": endpoints,
        "frozen_files_sha256": frozen, "historical_files_sha256": history,
        "selection_evidence": {"experiment_id": selection["experiment_id"],
                               "source": "Platform WebAgent/AgentServer (OpenCode)",
                               "baseline_audit_sha256": sha(selection_path)},
        "outcomes": OUTCOMES,
        "limitations": ["descriptive_one_attempt_per_case", "single_configuration_without_concurrent_control",
                        "historical_069_072_are_context_only", "not_webagent_reproduction",
                        "precise_master_duration_unavailable", "1200_seconds_not_proven_sufficient",
                        "provider_cache_and_resource_contention_uncontrolled", "public_projection_is_not_os_sandbox"],
    }
    for directory in (HERE, CAMPAIGN):
        write_new(directory / "manifest.json", manifest)
        with (directory / "manifest.sha256").open("x") as stream:
            stream.write(sha(directory / "manifest.json") + "\n")
    print(json.dumps({"prepared": True, "campaign_id": CAMPAIGN_ID,
                      "manifest_sha256": sha(HERE / "manifest.json"), "model_calls": 0}))


if __name__ == "__main__":
    main()
