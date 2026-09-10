"""Independent, read-only prelaunch audit. Never loads credentials or calls a provider."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from famou.effect_adapters import famou_case_content_digest
from famou.effect_trial import TrialBaseline, TrialSuite
from famou.profiles import ModelProfile
from famou.staged_workflow import StagedWorkflowConfig

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
IMPLEMENTATION = "5c89e049c184c52090f665131e3290ea3359bc04"
CAMPAIGN_ID = "real-eval-glm-5.2-master-budget-20260910"
PROFILE_SHA = "da362bcb878a675f2c92dab88d022cfa40f6ef95db54871deb8f71e481c4968b"
ORDER = [("master_300", "sheet_metal_nesting"), ("master_1200", "china_post_pickup_optimization"),
         ("master_1200", "sheet_metal_nesting"), ("master_300", "china_post_pickup_optimization")]
POLICIES = {f"master_{seconds}": {
    "master_seconds": seconds, "build_seconds": 2400, "reserve_seconds": 120,
    "checkpoint_after_rounds": 32,
} for seconds in (300, 1200)}
LEGACY_ROOT = "specs/069-webagent-normal-workflow"
SEALED_HISTORY = {
    f"{LEGACY_ROOT}/measurement/manifest.json": "07781f3390586e49c2c521012e7981350c06215e6c7103a865a97f25597e423e",
    f"{LEGACY_ROOT}/measurement/prelaunch-audit.json": "adbeb46bf746c329deea711e14dfc17ede44bcda91e947b215453f836fc9719c",
    f"{LEGACY_ROOT}/measurement/dry-run.json": "75acbe842b3c7286826d912840b6cbaa6e3482efb85e2e796830bbdc9b7ae4cc",
    f"{LEGACY_ROOT}/postrun/final-audit.json": "3175509fe7d2df7210047ec956ad2f24049189524adfe5670586704ec6cdb2e7",
    f"{LEGACY_ROOT}/postrun/final-report.md": "b5c615539444985dfa28bb9fc1ab04908fd91b361421dbe14f2aa2dfaabe2a97",
}
CEILINGS = {"max_wall_seconds": 5400, "max_tool_steps": 200,
            "max_total_tokens": 8_000_000, "max_cost_micros": None}
CASE_PINS = {
    "sheet_metal_nesting": {
        "digest": "sha256:dabc2e7b1ee860cd2a07a4f6c066a62aad4b5d49804d1ae76d1fdd2ed957c99e",
        "revision_id": "93616a97-8980-4348-a113-c18fafe2e40b",
        "evaluator_sha256": "9b17036381b3dbbd9687123e07cb569f7c668e13d5b570587db653916437bcae",
    },
    "china_post_pickup_optimization": {
        "digest": "sha256:1d2c1cbe0b7a3fd7cdc43d40106c714b3244485a13318b4d110dc393556e4429",
        "revision_id": "a313810d-a09f-4c4f-8669-9bbbd3d87215",
        "evaluator_sha256": "e357ad103e82628f6f321beac88e73303907d85e1d63bddfce3f86718e7efbc4",
    },
}
EXTRACTOR_SHA = "858e1a84c6a7c57472a141a353ca3a4ea3895aa614435c4d43a1a10ae3f1028b"
HASH = re.compile(r"[0-9a-f]{64}")


class AuditError(ValueError):
    """A bounded diagnostic without private paths or provider configuration."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def canonical(value, *, newline=False):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode()
    return raw + (b"\n" if newline else b"")


def object_sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    require(path.is_file() and not path.is_symlink(), "expected regular frozen file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024,
            "expected bounded JSON evidence")
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), "expected JSON object evidence")
    return value


def confined(root, relative):
    require(isinstance(relative, str), "expected relative evidence path")
    path = Path(relative)
    require(not path.is_absolute() and relative == path.as_posix()
            and path.parts and not any(part in {".", ".."} for part in path.parts),
            "evidence path escaped repository")
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        require(not candidate.is_symlink(), "linked evidence path")
    return candidate


def check_map(repo, mapping):
    require(isinstance(mapping, dict) and bool(mapping), "missing frozen digest map")
    for relative, digest in mapping.items():
        require(isinstance(digest, str) and HASH.fullmatch(digest), "invalid frozen digest")
        require(sha(confined(repo, relative)) == digest, "frozen evidence digest mismatch")


def check_source(repo, manifest):
    require(manifest["implementation_commit"] == IMPLEMENTATION, "wrong implementation commit")
    mapping = manifest["source_files_sha256"]
    check_map(repo, mapping)
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", IMPLEMENTATION, "--", "src/famou"], cwd=repo,
        stderr=subprocess.DEVNULL, text=True,
    ).splitlines()
    expected = {path for path in tracked if path.endswith(".py")}
    actual = {path.relative_to(repo).as_posix() for path in (repo / "src/famou").rglob("*.py")}
    require(set(mapping) == expected == actual, "source file set differs from pinned commit")
    for relative, digest in mapping.items():
        blob = subprocess.check_output(["git", "show", f"{IMPLEMENTATION}:{relative}"], cwd=repo,
                                       stderr=subprocess.DEVNULL)
        require(hashlib.sha256(blob).hexdigest() == digest, "source bytes differ from pinned commit")
    require(object_sha(mapping) == manifest["source_sha256"], "source aggregate digest mismatch")


def check_history(repo, manifest):
    """The sealed registration supplies context pins, never new control observations."""
    check_map(repo, SEALED_HISTORY)
    sealed = read(repo / LEGACY_ROOT / "measurement/manifest.json")
    expected = {**sealed["historical_files_sha256"], **SEALED_HISTORY}
    require(manifest["historical_files_sha256"] == expected,
            "historical evidence differs from sealed context")
    check_map(repo, expected)
    final = read(repo / LEGACY_ROOT / "postrun/final-audit.json")
    require(final["passed"] is True and final["complete"] is True
            and final["final_acceptance"] is True
            and final["manifest_sha256"] == SEALED_HISTORY[f"{LEGACY_ROOT}/measurement/manifest.json"],
            "historical campaign was not finally sealed")


def frozen_paths(repo, campaign, here):
    paths = [*sorted((campaign / "inputs").glob("*.json")), campaign / "readiness.json",
             *sorted(here.glob("*.py")), *sorted((here.parent / "postrun").glob("*.py")),
             *sorted((repo / "tests").rglob("*.py")),
             *sorted((repo / LEGACY_ROOT / "measurement").glob("*.py")),
             repo / LEGACY_ROOT / "postrun/audit.py", repo / LEGACY_ROOT / "postrun/render_report.py",
             repo / ".lunar/real-eval-20260908/ccswitch.py", repo / ".venv/bin/lunar-agent",
             repo / ".lunar/harness-venv-high-score-20260909/bin/python"]
    return {path.relative_to(repo).as_posix() for path in paths}


def check_frozen(repo, campaign, manifest, here):
    required = frozen_paths(repo, campaign, here)
    for relative in ("measurement/prepare.py", "measurement/audit.py", "measurement/dry_run.py",
                     "measurement/adapter.py", "measurement/worker.py", "measurement/campaign.py",
                     "postrun/audit.py", "postrun/render_report.py", "postrun/test_audit.py"):
        require((here.parent / relative).relative_to(repo).as_posix() in required,
                "missing registered execution or reporting script")
    require(set(manifest["frozen_files_sha256"]) == required, "incomplete executable or input freeze")
    check_map(repo, manifest["frozen_files_sha256"])
    legacy = {relative for relative in required if relative.startswith(LEGACY_ROOT + "/")}
    for relative in legacy:
        blob = subprocess.check_output(["git", "show", f"{IMPLEMENTATION}:{relative}"],
                                       cwd=repo, stderr=subprocess.DEVNULL)
        require(hashlib.sha256(blob).hexdigest() == manifest["frozen_files_sha256"][relative],
                "reused helper differs from pinned commit")


def check_unstarted(campaign):
    require(campaign.is_dir() and not campaign.is_symlink(), "missing unstarted campaign directory")
    require(not any(os.path.lexists(campaign / name)
                    for name in ("slots", "started.json", "terminated.json", "summary.json"))
            and not any(re.fullmatch(r"slot-\d+-(started|terminated)\.json", path.name)
                        for path in campaign.iterdir()), "prelaunch audit requires unstarted slots")


def check_schedule(manifest):
    require(manifest["schema_version"] == "1" and manifest["campaign_id"] == CAMPAIGN_ID,
            "wrong campaign identity")
    require(manifest["planned_attempts"] == 4 and manifest["policies"] == POLICIES,
            "fixed denominator or stage policy changed")
    require(manifest["execution"] == {
        "waves": [[1, 2], [3, 4]], "concurrency": 2, "subject_outer_seconds": 5430,
        "harness_outer_seconds": 3630, "slot_outer_seconds": 9300,
    }, "fixed execution schedule changed")
    slots = manifest["slots"]
    require(isinstance(slots, list) and len(slots) == 4, "wrong slot count")
    for index, (slot, (budget_arm, key)) in enumerate(zip(slots, ORDER, strict=True), 1):
        require(set(slot) == {"index", "arm", "budget_arm", "case_key", "request_sha256", "workflow_config"},
                "unexpected slot fields")
        require(type(slot["index"]) is int
                and (slot["index"], slot["arm"], slot["budget_arm"], slot["case_key"])
                == (index, "S", budget_arm, key), "fixed slot order changed")
    require(manifest["outcomes"] == {
        "primary": "per-case exact-harness validity after accepted subject receipt",
        "unscored_failure": None, "pooled_quality_mean": False,
        "fixed_denominator_per_budget_arm": 2, "retries_or_replacements": 0,
        "historical_attempts_in_denominator": 0,
        "secondary": "validated Master plan handoff and observed Build evidence",
        "master_duration_seconds": None,
    }, "outcome or stopping protocol changed")


def request_for(suite, profile_sha):
    case = suite.cases[0]
    return {
        "schema_version": "1", "mode": "normal", "benchmark": suite.benchmark.to_dict(),
        "case": case.public_identity(), "run_index": 1, "requested_model": "glm-5.2",
        "model_profile_sha256": profile_sha, "entrypoint": case.entrypoint,
        "public_files": [descriptor.to_dict() for descriptor in case.public_files],
        "receipt_path": "receipt.json",
    }


def check_workflow(manifest, slot, request):
    request_sha = hashlib.sha256(canonical(request, newline=True)).hexdigest()
    require(slot["request_sha256"] == request_sha, "subject request digest mismatch")
    require(slot["arm"] == "S" and slot["budget_arm"] in POLICIES, "all slots require registered staged groups")
    workflow = StagedWorkflowConfig.from_dict(slot["workflow_config"]).to_dict()
    index = slot["index"]
    require(workflow == {
        "manifest": {
            "run_id": f"{CAMPAIGN_ID}-slot-{index:03d}",
            "attempt_id": f"slot-{index:03d}-attempt-001",
            "source_sha256": manifest["source_sha256"], "suite_key": request["benchmark"]["name"],
            "case_key": slot["case_key"], "request_sha256": request_sha,
            "model_profile_sha256": manifest["profile_sha256"], "ceilings": CEILINGS,
        }, "policy": POLICIES[slot["budget_arm"]],
    }, "workflow does not bind this exact attempt and shared budget")


def check_cases(repo, campaign, manifest, old):
    require(set(manifest["cases"]) == set(CASE_PINS), "selected cases changed")
    selection_rel = ".lunar/high-score-case-selection-20260909/baseline-audit.json"
    selection = read(confined(repo, selection_rel))
    require(manifest["selection_evidence"] == {
        "experiment_id": selection["experiment_id"],
        "source": "Platform WebAgent/AgentServer (OpenCode)",
        "baseline_audit_sha256": sha(repo / selection_rel),
    }, "historical selection identity changed")
    require(selection["model"] == "glm-5.2" and selection["agent_family"] == "AgentServer/OpenCode",
            "historical model or agent identity mismatch")
    requests = {}
    for key, pins in CASE_PINS.items():
        record = manifest["cases"][key]
        require(set(record) == {"suite", "public_root_rel", "private_root_rel"},
                "unexpected case fields")
        suite = TrialSuite.from_dict(record["suite"])
        require(len(suite.cases) == 1 and suite.cases[0].key == key, "suite case mismatch")
        case = suite.cases[0]
        prior = next(slot for slot in old["slots"] if slot["case_key"] == key)
        require(case.digest == pins["digest"] == prior["case_digest"]
                and case.revision_id == pins["revision_id"], "case revision changed")
        require(case.harness.to_dict() == prior["harness"] == {
            "evaluator_sha256": pins["evaluator_sha256"], "extractor_sha256": EXTRACTOR_SHA,
        }, "exact harness identity changed")
        kit_rel = f".lunar/high-score-case-selection-20260909/kit-build/{key}"
        require(record["public_root_rel"] == kit_rel + "/public"
                and record["private_root_rel"] == kit_rel + "/private", "case source roots changed")
        kit = confined(repo, kit_rel)
        original_suite = read(kit / "suite.json")
        require(record["suite"] == original_suite == read(campaign / "inputs" / f"{key}-suite.json"),
                "suite bytes or projection changed")
        require(sha(kit / "suite.json") == prior["suite_sha256"], "historical suite digest mismatch")
        require(famou_case_content_digest(kit / "private") == pins["digest"],
                "actual private case content changed")
        for name, digest in (("extractor_agent.py", EXTRACTOR_SHA),
                             ("evaluator.py", pins["evaluator_sha256"])):
            require(sha(kit / "private/tests" / name) == digest, "actual exact harness bytes changed")
        public = kit / "public"
        observed = set()
        for path in public.rglob("*"):
            require(not path.is_symlink(), "linked public case source")
            if path.is_file():
                observed.add(path.relative_to(public).as_posix())
        require(observed == {descriptor.path for descriptor in case.public_files},
                "unexpected public projection files")
        for descriptor in case.public_files:
            path = confined(public, descriptor.path)
            require(sha(path) == descriptor.sha256 and path.stat().st_size == descriptor.size,
                    "actual public input differs from frozen descriptor")
        baseline = read(campaign / "inputs" / f"{key}-baseline.json")
        TrialBaseline.from_dict(baseline)
        require(baseline["schema_version"] == "1" and baseline["source"] == "company-platform"
                and baseline["benchmark"] == suite.benchmark.to_dict()
                and baseline["evaluation_profile"] == suite.evaluation_profile.to_dict()
                and baseline["model"] == {"requested": "glm-5.2", "effective": "glm-5.2",
                                           "evidence": "provider_observed"}
                and baseline["authority"] == "descriptive" and baseline["conclusion_eligibility"] == "ineligible"
                and baseline["provenance"] == {"source": "company-platform", "adapter": "agentserver"}
                and baseline["experiment_id"] == selection["experiment_id"], "baseline authority changed")
        observations = selection["by_case"][key]["runs"]
        require(len(observations) == 3 and all(
            row["validity_score"] == 1 and row["evaluation_status"] == "scored"
            and row["extraction_status"] == "extracted" and row["conclusion_eligibility"] == "eligible"
            for row in observations), "historical three-of-three selection changed")
        require(baseline["cases"] == [{**case.public_identity(), "harness": case.harness.to_dict(),
            "runs": [{"run_index": row["run_index"] + 1, "ready": True,
                      "extraction_status": "completed", "validity_score": row["validity_score"],
                      "overall_score": row["overall_score"]} for row in observations]}],
            "baseline observations changed")
        requests[key] = request_for(suite, manifest["profile_sha256"])
    for slot in manifest["slots"]:
        check_workflow(manifest, slot, requests[slot["case_key"]])
        if slot["arm"] == "S":
            require(read(campaign / "inputs" / f"slot-{slot['index']:03d}-workflow.json")
                    == slot["workflow_config"], "staged configuration file changed")
    for key in CASE_PINS:
        require(len({slot["request_sha256"] for slot in manifest["slots"] if slot["case_key"] == key}) == 1,
                "same-case arms receive different request bytes")


def audit(manifest_path, campaign_path, *, repo=REPO):
    """Return bounded evidence; caller owns persistence. No startup markers are created."""
    manifest_path, campaign, repo = Path(manifest_path).absolute(), Path(campaign_path).absolute(), Path(repo).absolute()
    require(campaign == repo / ".lunar" / CAMPAIGN_ID and not campaign.is_symlink(),
            "wrong local campaign directory")
    require(manifest_path == repo / "specs/072-master-budget-measurement/measurement/manifest.json",
            "wrong committed registration path")
    import famou
    require(Path(famou.__file__).resolve().parent == repo / "src/famou", "wrong imported product source")
    manifest = read(manifest_path)
    require(set(manifest) == {
        "schema_version", "campaign_id", "registered_utc", "implementation_commit", "source_files_sha256",
        "source_sha256", "profile", "profile_sha256", "policies", "execution", "planned_attempts", "cases",
        "slots", "endpoints", "frozen_files_sha256", "historical_files_sha256", "selection_evidence",
        "outcomes", "limitations",
    }, "unexpected registration fields")
    digest = sha(manifest_path)
    require(manifest_path.read_bytes() == (campaign / "manifest.json").read_bytes(),
            "committed and local registrations differ")
    for directory in (manifest_path.parent, campaign):
        require((directory / "manifest.sha256").read_text().strip() == digest, "manifest sidecar mismatch")
    check_unstarted(campaign)
    check_schedule(manifest)
    check_source(repo, manifest)
    check_history(repo, manifest)
    input_names = {"profile.json", *(f"{key}-{kind}.json" for key in CASE_PINS for kind in ("suite", "baseline")),
                   *(f"slot-{index:03d}-workflow.json" for index in range(1, 5))}
    require({path.name for path in (campaign / "inputs").iterdir()} == input_names,
            "unexpected campaign input files")
    check_frozen(repo, campaign, manifest, manifest_path.parent)
    profile = ModelProfile.from_dict(manifest["profile"])
    require(profile.to_dict() == read(campaign / "inputs/profile.json")
            and object_sha(profile.to_dict()) == manifest["profile_sha256"] == PROFILE_SHA,
            "model profile changed")
    old_root = repo / ".lunar/real-eval-glm-5.2-high-score-20260909"
    old = read(old_root / "manifest.json")
    require(sha(old_root / "manifest.json") == (old_root / "manifest.sha256").read_text().strip(),
            "historical manifest changed")
    require(manifest["endpoints"] == {
        "FAMOU_MODEL_ENDPOINT": old["identity"]["subject_endpoint_sha256"],
        "ANTHROPIC_BASE_URL": old["identity"]["extractor_endpoint_sha256"],
    } and all(isinstance(value, str) and HASH.fullmatch(value) for value in manifest["endpoints"].values()),
        "declared endpoint identity changed")
    check_cases(repo, campaign, manifest, old)
    # Inspect the installed runtime directly; preparation's booleans grant no authority.
    probe = ('import json, platform; from importlib.metadata import distributions; '
             'print(json.dumps({"python_version":platform.python_version(),"packages":'
             '{d.metadata["Name"].lower().replace("_","-"):d.version for d in distributions()}}))')
    harness_python = repo / ".lunar/harness-venv-high-score-20260909/bin/python"
    actual = json.loads(subprocess.check_output(
        [str(harness_python), "-c", probe], env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        stderr=subprocess.DEVNULL, text=True, timeout=30,
    ))
    old_readiness, readiness = read(old_root / "readiness.json"), read(campaign / "readiness.json")
    require(actual["packages"] == readiness["packages"] == old_readiness["packages"]
            and actual["python_version"] == readiness["python_version"] == old_readiness["python_version"],
            "installed harness dependency identity changed")
    require(sha(harness_python) == old["harness_python_sha256"] == readiness["harness_python_sha256"],
            "actual harness launcher changed")
    return {
        "schema_version": "1", "kind": "feature072_independent_prelaunch_audit", "status": "passed", "passed": True,
        "checked_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest,
        "implementation_commit": IMPLEMENTATION, "planned_attempts": 4, "model_calls": 0,
        "credentials_loaded": False, "checks": {
            "git_source_bytes": True, "frozen_and_historical_bytes": True,
            "sealed_history_is_context_only": True, "reused_helper_git_bytes": True,
            "fixed_schedule_and_denominator": True, "same_case_request_bytes": True,
            "workflow_identity_and_aggregate_limits": True, "public_and_private_case_bytes": True,
            "exact_harness_bytes_and_installed_versions": True, "unstarted_attempts": True,
        }, "limitations": ["endpoint_configuration_rechecked_by_launcher_without_persisting_keys",
                            "public_projection_is_not_an_os_sandbox",
                            "one_attempt_per_case_arm_is_descriptive",
                            "candidate_files_and_checkpoints_do_not_establish_validity"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.manifest, args.campaign)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, AuditError) else "malformed or unavailable audit evidence"
        print(json.dumps({"status": "failed", "model_calls": 0, "error": message}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
