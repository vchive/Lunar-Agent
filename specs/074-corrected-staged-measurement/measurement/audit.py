"""Independent two-slot preaudit using pinned, explicitly bound prior byte validators."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from adapter import HELPER_FILES, load_prior

from famou.profiles import ModelProfile
from famou.staged_workflow import StagedWorkflowConfig

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
IMPLEMENTATION = "c28e498e539b3ed6e37d743145ba1c38f9b1e9e2"
CAMPAIGN_ID = "real-eval-glm-5.2-corrected-staged-20260910"
ORDER = [("master_1200", "sheet_metal_nesting"), ("master_1200", "china_post_pickup_optimization")]
POLICIES = {"master_1200": {"master_seconds": 1200, "build_seconds": 2400,
                             "reserve_seconds": 120, "checkpoint_after_rounds": 32}}
EXECUTION = {"waves": [[1, 2]], "concurrency": 2, "subject_outer_seconds": 5430,
             "harness_outer_seconds": 3630, "slot_outer_seconds": 9300}
OUTCOMES = {
    "primary": "per-case exact-harness validity after accepted subject receipt",
    "unscored_failure": None, "pooled_quality_mean": False, "fixed_denominator_per_budget_arm": 2,
    "retries_or_replacements": 0, "historical_attempts_in_denominator": 0,
    "secondary": "validated Master plan handoff and observed Build evidence", "master_duration_seconds": None,
}
PRIOR_ROOT = "specs/072-master-budget-measurement"
SEALED_HISTORY = {f"{PRIOR_ROOT}/{relative}": digest for relative, digest in {
    "measurement/manifest.json": "cbdb07e22b08a8944b9e80bf7f30cbd4057b931bd6128077dcf5da533834f830",
    "measurement/prelaunch-audit.json": "a5e210faf369b0133c567197f4ea3a33327772ccab601251b7e72613dbbd2132",
    "measurement/dry-run.json": "7609a3beb2aec800ad1a5e094a29cef4a8cfe2ab882b821bc10430e2f7de5801",
    "postrun/final-audit.json": "2973625674cc0056e8891e384b6feeb021ba1174b217e10d3c633cf23232480f",
    "postrun/final-report.md": "10e6399291146c75e4abad942c908af6bbad652f3a5f999522c17fda6f0c15b4",
}.items()}
EXPECTED_HELPERS = {
    *(f"specs/069-webagent-normal-workflow/measurement/{name}.py"
      for name in ("prepare", "audit", "dry_run", "worker", "campaign")),
    "specs/069-webagent-normal-workflow/postrun/audit.py",
    "specs/069-webagent-normal-workflow/postrun/render_report.py",
    *(f"{PRIOR_ROOT}/measurement/{name}.py" for name in ("adapter", "audit", "prepare", "dry_run")),
    f"{PRIOR_ROOT}/postrun/audit.py",
}
REQUIRED_CODE = (
    *(f"measurement/{name}.py" for name in ("adapter", "prepare", "audit", "dry_run", "worker", "campaign")),
    "postrun/audit.py", "postrun/render_report.py", "postrun/test_audit.py",
)

# This private instance only supplies parameter-independent validators. Its four-slot top-level
# audit/schedule/history/freeze entry points are never called, and no historical manifest changes.
native = load_prior("audit", overrides={"IMPLEMENTATION": IMPLEMENTATION, "CAMPAIGN_ID": CAMPAIGN_ID,
                                        "POLICIES": POLICIES})
AuditError, require = native.AuditError, native.require
sha, read, confined, canonical, object_sha = native.sha, native.read, native.confined, native.canonical, native.object_sha
check_map, check_source, check_unstarted = native.check_map, native.check_source, native.check_unstarted
request_for, CASE_PINS, PROFILE_SHA, CEILINGS = native.request_for, native.CASE_PINS, native.PROFILE_SHA, native.CEILINGS


def check_schedule(manifest):
    require(manifest["schema_version"] == "1" and manifest["campaign_id"] == CAMPAIGN_ID,
            "wrong campaign identity")
    require(manifest["planned_attempts"] == 2 and manifest["policies"] == POLICIES
            and manifest["execution"] == EXECUTION and manifest["outcomes"] == OUTCOMES,
            "two-slot policy, schedule or outcome protocol changed")
    slots = manifest["slots"]
    require(isinstance(slots, list) and len(slots) == 2, "wrong slot count")
    for index, (slot, (group, case)) in enumerate(zip(slots, ORDER, strict=True), 1):
        require(set(slot) == {"index", "arm", "budget_arm", "case_key", "request_sha256", "workflow_config"}
                and type(slot["index"]) is int
                and (slot["index"], slot["arm"], slot["budget_arm"], slot["case_key"])
                == (index, "S", group, case), "fixed two-slot identity changed")


def check_workflow(manifest, slot, request):
    digest = hashlib.sha256(canonical(request, newline=True)).hexdigest()
    require(slot["request_sha256"] == digest, "subject request digest mismatch")
    require(slot["arm"] == "S" and slot["budget_arm"] == "master_1200", "wrong staged configuration")
    workflow = StagedWorkflowConfig.from_dict(slot["workflow_config"]).to_dict()
    index = slot["index"]
    require(workflow == {"manifest": {
        "run_id": f"{CAMPAIGN_ID}-slot-{index:03d}", "attempt_id": f"slot-{index:03d}-attempt-001",
        "source_sha256": manifest["source_sha256"], "suite_key": request["benchmark"]["name"],
        "case_key": slot["case_key"], "request_sha256": digest,
        "model_profile_sha256": manifest["profile_sha256"], "ceilings": CEILINGS,
    }, "policy": POLICIES["master_1200"]}, "workflow does not bind this attempt and shared budget")


native.check_workflow = check_workflow
check_cases = native.check_cases


def historical_map(repo):
    check_map(repo, SEALED_HISTORY)
    sealed = read(repo / PRIOR_ROOT / "measurement/manifest.json")
    final = read(repo / PRIOR_ROOT / "postrun/final-audit.json")
    require(final["passed"] is True and final["complete"] is True and final["final_acceptance"] is True
            and final["manifest_sha256"] == SEALED_HISTORY[f"{PRIOR_ROOT}/measurement/manifest.json"],
            "historical campaign lacks a matching final seal")
    result = {**sealed["historical_files_sha256"], **SEALED_HISTORY}
    check_map(repo, result)
    return result


def check_history(repo, manifest):
    require(manifest["historical_files_sha256"] == historical_map(repo), "sealed historical context changed")


def code_paths(repo, here):
    require(set(HELPER_FILES) == EXPECTED_HELPERS, "incomplete pinned helper closure")
    paths = {*here.glob("*.py"), *(here.parent / "postrun").glob("*.py"), *(repo / "tests").rglob("*.py")}
    required = {*(here.parent / name for name in REQUIRED_CODE),
                repo / "tests/test_measurement074_audit.py", repo / "tests/test_measurement074_runner.py"}
    require(required <= paths, "missing required execution, reporting or test script")
    return {path.relative_to(repo).as_posix() for path in paths} | set(HELPER_FILES)


def frozen_paths(repo, campaign, here):
    return code_paths(repo, here) | {
        *(path.relative_to(repo).as_posix() for path in (campaign / "inputs").glob("*.json")),
        (campaign / "readiness.json").relative_to(repo).as_posix(),
        ".lunar/real-eval-20260908/ccswitch.py", ".venv/bin/lunar-agent",
        ".lunar/harness-venv-high-score-20260909/bin/python",
    }


def check_frozen(repo, campaign, manifest, here):
    pins = manifest["frozen_files_sha256"]
    require(set(pins) == frozen_paths(repo, campaign, here), "incomplete executable or input freeze")
    check_map(repo, pins)
    for relative, digest in HELPER_FILES.items():
        require(pins[relative] == digest, "pinned helper identity changed")
        blob = subprocess.check_output(["git", "show", f"{IMPLEMENTATION}:{relative}"],
                                       cwd=repo, stderr=subprocess.DEVNULL)
        require(hashlib.sha256(blob).hexdigest() == digest, "helper differs from implementation commit")


def check_runtime(repo, campaign, old):
    launcher = repo / ".lunar/harness-venv-high-score-20260909/bin/python"
    readiness = read(campaign / "readiness.json")
    require(sha(launcher) == old["harness_python_sha256"] == readiness["harness_python_sha256"],
            "harness launcher changed")
    probe = ('import json, platform; from importlib.metadata import distributions; '
             'print(json.dumps({"python_version":platform.python_version(),"packages":'
             '{d.metadata["Name"].lower().replace("_","-"):d.version for d in distributions()}}))')
    actual = json.loads(subprocess.check_output(
        [str(launcher), "-c", probe], env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        stderr=subprocess.DEVNULL, text=True, timeout=30,
    ))
    prior = read(repo / ".lunar/real-eval-glm-5.2-high-score-20260909/readiness.json")
    require(all(actual[name] == readiness[name] == prior[name] for name in ("python_version", "packages")),
            "installed harness dependency identity changed")


def audit(manifest_path, campaign_path, *, repo=REPO):
    manifest_path, campaign, repo = Path(manifest_path).absolute(), Path(campaign_path).absolute(), Path(repo).absolute()
    expected_manifest = "specs/074-corrected-staged-measurement/measurement/manifest.json"
    require(manifest_path == confined(repo, expected_manifest)
            and campaign == confined(repo, f".lunar/{CAMPAIGN_ID}"), "wrong registration paths")
    import famou
    require(Path(famou.__file__).resolve().parent == repo / "src/famou", "wrong imported product source")
    manifest, digest = read(manifest_path), sha(manifest_path)
    require(set(manifest) == {
        "schema_version", "campaign_id", "registered_utc", "implementation_commit", "source_files_sha256",
        "source_sha256", "profile", "profile_sha256", "policies", "execution", "planned_attempts", "cases",
        "slots", "endpoints", "frozen_files_sha256", "historical_files_sha256", "selection_evidence",
        "outcomes", "limitations",
    }, "unexpected registration fields")
    require(manifest_path.read_bytes() == (campaign / "manifest.json").read_bytes(), "local registration differs")
    for directory in (manifest_path.parent, campaign):
        anchor = directory / "manifest.sha256"
        require(not anchor.is_symlink() and anchor.read_text().strip() == digest, "manifest sidecar mismatch")
    check_unstarted(campaign)
    check_schedule(manifest)
    check_source(repo, manifest)
    check_history(repo, manifest)
    names = {"profile.json", *(f"{key}-{kind}.json" for key in CASE_PINS for kind in ("suite", "baseline")),
             "slot-001-workflow.json", "slot-002-workflow.json"}
    require({path.name for path in (campaign / "inputs").iterdir()} == names, "unexpected campaign inputs")
    check_frozen(repo, campaign, manifest, manifest_path.parent)
    profile = ModelProfile.from_dict(manifest["profile"])
    require(profile.to_dict() == read(campaign / "inputs/profile.json")
            and object_sha(profile.to_dict()) == manifest["profile_sha256"] == PROFILE_SHA, "model profile changed")
    old = read(repo / ".lunar/real-eval-glm-5.2-high-score-20260909/manifest.json")
    require(manifest["endpoints"] == {"FAMOU_MODEL_ENDPOINT": old["identity"]["subject_endpoint_sha256"],
                                      "ANTHROPIC_BASE_URL": old["identity"]["extractor_endpoint_sha256"]},
            "authorized endpoint identity changed")
    check_cases(repo, campaign, manifest, old)
    check_runtime(repo, campaign, old)
    return {
        "schema_version": "1", "kind": "feature074_independent_prelaunch_audit", "status": "passed", "passed": True,
        "checked_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest,
        "implementation_commit": IMPLEMENTATION, "planned_attempts": 2, "model_calls": 0, "credentials_loaded": False,
        "checks": {"git_source_bytes": True, "frozen_and_historical_bytes": True,
                   "two_slot_schedule_and_denominator": True, "workflow_identity_and_aggregate_limits": True,
                   "public_and_private_case_bytes": True, "exact_harness_bytes_and_installed_versions": True,
                   "unstarted_attempts": True, "pinned_helper_closure": True},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.manifest, args.campaign)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "model_calls": 0, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
