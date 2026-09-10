"""Bind the sealed byte validators to a fresh registration of the public-plan correction."""
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
_bound_module.PRIOR_ROOT = "specs/074-corrected-staged-measurement"
_bound_module.SEALED_HISTORY = {
    _bound_module.PRIOR_ROOT + "/" + name: digest for name, digest in {
        "measurement/manifest.json": "b154975d9557b9697fcdc7915de3ab7bb225165c6aaa1c6c0ab3f432a2123229",
        "measurement/prelaunch-audit.json": "1871f7286a8b950c4c98ffce570f707472c1af562c4a9e4eb0e3f1a8c2c7a6ac",
        "measurement/dry-run.json": "c4e477878e7d89f77a3cb72a61da933e74407db3a7c327942102a6e777970404",
        "postrun/final-audit.json": "c0f38b2df844152a6a8bca13036a15a031fb0df3c9f5dc560818f4c5f0f1447a",
        "postrun/final-report.md": "a1c64aa7d248873c2d5636da3fdb98edcacd78a0943ce12d063abe6499f68503",
        "postrun/final-process-check.json": "b28e746f1b81b834b47c0526b81c40fdfb4fae863deb0db88755082169e15e70",
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
                repo / "tests/test_measurement076_audit.py", repo / "tests/test_measurement076_runner.py"}
    q.require(required <= paths, "missing required execution, reporting or test script")
    return {path.relative_to(repo).as_posix() for path in paths} | set(q.HELPER_FILES)


def audit(manifest_path, campaign_path, *, repo=REPO):
    """Use the original byte gates under the exact new paths; no old top-level audit is called."""
    q = _bound_module
    manifest_path, campaign, repo = Path(manifest_path).absolute(), Path(campaign_path).absolute(), Path(repo).absolute()
    q.require(manifest_path == q.confined(repo, "specs/076-public-plan-handoff-measurement/measurement/manifest.json")
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
        "schema_version": "1", "kind": "feature076_independent_prelaunch_audit", "passed": True, "status": "passed",
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
