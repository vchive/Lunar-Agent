"""Bind the sealed byte validators to a fresh registration of the Master planning-role clarification."""
from datetime import UTC, datetime
from pathlib import Path

from adapter import (
    CAMPAIGN_ID,
    EXECUTION,
    HELPER_FILES,
    HERE,
    IMPLEMENTATION,
    ORDER,
    POLICIES,
    REPO,
    load_previous,
)

_bound_module = load_previous("audit")
for _name, _value in {
    "REPO": REPO, "HERE": HERE, "IMPLEMENTATION": IMPLEMENTATION, "CAMPAIGN_ID": CAMPAIGN_ID,
    "ORDER": ORDER, "POLICIES": POLICIES, "EXECUTION": EXECUTION, "HELPER_FILES": HELPER_FILES,
}.items():
    setattr(_bound_module, _name, _value)
# check_source and check_cases belong to a separately loaded 072 module. Bind that module too;
# changing an exported constant alone would leave their actual function globals on old source.
for _name, _value in {
    "IMPLEMENTATION": IMPLEMENTATION, "CAMPAIGN_ID": CAMPAIGN_ID, "POLICIES": POLICIES,
}.items():
    setattr(_bound_module.native, _name, _value)
_bound_module.PRIOR_ROOT = "specs/076-public-plan-handoff-measurement"
_bound_module.SEALED_HISTORY = {
    _bound_module.PRIOR_ROOT + "/" + name: digest for name, digest in {
        "measurement/manifest.json": "6690a02223aa3ea34bd5f88d9482d75d4a087857d69edd4245ac04479a321b76",
        "measurement/prelaunch-audit.json": "d689ee3b3d319980ffbd3ed065dcbb7bdd2f87e699434ac5b5e36aa396ba04bb",
        "measurement/dry-run.json": "93a3abc931094149e3fff9c9f0e20a7d68e5f0c6141fa088ad3b97515e09ca2d",
        "postrun/final-audit.json": "95d54b9d3c349fd3f83bb0cb1c052694cb3e21247b6c8a21477017e31848b62e",
        "postrun/final-report.md": "88ab75a77ec0eede74dd0d1cb1c9a4513e9e2a3de8f58de5ced3f0afb7830f96",
        "postrun/final-process-check.json": "1349dd5d00190408938bf61f8b1318f3fe36880778f5687dfd9ffbdc115aaf57",
    }.items()
}
# An independent path set prevents the adapter from silently omitting a transitive helper.
_bound_module.EXPECTED_HELPERS = {
    *(f"specs/069-webagent-normal-workflow/measurement/{name}.py"
      for name in ("prepare", "audit", "dry_run", "worker", "campaign")),
    "specs/069-webagent-normal-workflow/postrun/audit.py",
    "specs/069-webagent-normal-workflow/postrun/render_report.py",
    *(f"specs/072-master-budget-measurement/measurement/{name}.py"
      for name in ("adapter", "audit", "prepare", "dry_run")),
    "specs/072-master-budget-measurement/postrun/audit.py",
    *(f"specs/074-corrected-staged-measurement/measurement/{name}.py"
      for name in ("adapter", "prepare", "audit", "dry_run", "worker", "campaign")),
    *(f"specs/074-corrected-staged-measurement/postrun/{name}.py"
      for name in ("audit", "render_report", "test_audit")),
    "tests/test_measurement074_audit.py", "tests/test_measurement074_runner.py",
}


def code_paths(repo, here):
    q = _bound_module
    q.require(set(q.HELPER_FILES) == q.EXPECTED_HELPERS, "incomplete pinned helper closure")
    paths = {*here.glob("*.py"), *(here.parent / "postrun").glob("*.py"),
             *(repo / "tests").rglob("*.py")}
    required = {*(here.parent / name for name in q.REQUIRED_CODE),
                repo / "tests/test_measurement078_audit.py", repo / "tests/test_measurement078_runner.py"}
    q.require(required <= paths, "missing required execution, reporting or test script")
    return {path.relative_to(repo).as_posix() for path in paths} | set(q.HELPER_FILES)


def audit(manifest_path, campaign_path, *, repo=REPO):
    """Use the original byte gates under the exact new paths; no old top-level audit is called."""
    q = _bound_module
    manifest_path, campaign, repo = Path(manifest_path).absolute(), Path(campaign_path).absolute(), Path(repo).absolute()
    q.require(manifest_path == q.confined(repo, "specs/078-master-planning-role-measurement/measurement/manifest.json")
              and campaign == q.confined(repo, f".lunar/{q.CAMPAIGN_ID}"), "wrong registration paths")
    import famou
    q.require(Path(famou.__file__).resolve().parent == repo / "src/famou", "wrong imported product source")
    manifest, digest = q.read(manifest_path), q.sha(manifest_path)
    q.require(set(manifest) == {
        "schema_version", "campaign_id", "registered_utc", "implementation_commit", "source_files_sha256",
        "source_sha256", "profile", "profile_sha256", "policies", "execution", "planned_attempts", "cases",
        "slots", "endpoints", "frozen_files_sha256", "historical_files_sha256", "selection_evidence",
        "outcomes", "limitations",
    }, "unexpected registration fields")
    q.require(manifest_path.read_bytes() == (campaign / "manifest.json").read_bytes(), "local registration differs")
    for directory in (manifest_path.parent, campaign):
        anchor = directory / "manifest.sha256"
        q.require(not anchor.is_symlink() and anchor.read_text().strip() == digest, "manifest sidecar mismatch")
    q.check_unstarted(campaign)
    q.check_schedule(manifest)
    q.check_source(repo, manifest)
    q.check_history(repo, manifest)
    names = {"profile.json", *(f"{key}-{kind}.json" for key in q.CASE_PINS for kind in ("suite", "baseline")),
             "slot-001-workflow.json", "slot-002-workflow.json"}
    q.require({path.name for path in (campaign / "inputs").iterdir()} == names, "unexpected campaign inputs")
    q.check_frozen(repo, campaign, manifest, manifest_path.parent)
    profile = q.ModelProfile.from_dict(manifest["profile"])
    q.require(profile.to_dict() == q.read(campaign / "inputs/profile.json")
              and q.object_sha(profile.to_dict()) == manifest["profile_sha256"] == q.PROFILE_SHA, "model profile changed")
    old = q.read(repo / ".lunar/real-eval-glm-5.2-high-score-20260909/manifest.json")
    q.require(manifest["endpoints"] == {
        "FAMOU_MODEL_ENDPOINT": old["identity"]["subject_endpoint_sha256"],
        "ANTHROPIC_BASE_URL": old["identity"]["extractor_endpoint_sha256"],
    }, "authorized endpoint identity changed")
    q.check_cases(repo, campaign, manifest, old)
    q.check_runtime(repo, campaign, old)
    return {
        "schema_version": "1", "kind": "feature078_independent_prelaunch_audit", "passed": True, "status": "passed",
        "checked_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest,
        "implementation_commit": q.IMPLEMENTATION, "planned_attempts": 2, "model_calls": 0, "credentials_loaded": False,
        "checks": {"git_source_bytes": True, "frozen_and_historical_bytes": True,
                   "two_slot_schedule_and_denominator": True, "workflow_identity_and_aggregate_limits": True,
                   "public_and_private_case_bytes": True, "exact_harness_bytes_and_installed_versions": True,
                   "unstarted_attempts": True, "pinned_helper_closure": True},
    }


_bound_module.code_paths = code_paths
_bound_module.audit = audit
_bound_module.__file__ = __file__


def __getattr__(name):
    return getattr(_bound_module, name)


if __name__ == "__main__":
    raise SystemExit(_bound_module.main())
