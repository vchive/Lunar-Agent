"""Read-only two-slot audit using pinned native receipt and workflow validators."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
MEASUREMENT = HERE.parent / "measurement"


def load_file(name, path):
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def dependencies():
    adapter = load_file("postrun074_adapter", MEASUREMENT / "adapter.py")
    return adapter, adapter.load_legacy("postrun")


def verify_registration(manifest_path, campaign, evidence, adapter, legacy):
    manifest = evidence.json(manifest_path)
    digest = evidence.track(manifest_path)
    legacy.require(manifest_path.read_bytes() == (campaign / "manifest.json").read_bytes(),
                   "campaign and registered manifest differ")
    evidence.track(campaign / "manifest.json")
    for directory in (manifest_path.parent, campaign):
        evidence.track(directory / "manifest.sha256")
        legacy.require((directory / "manifest.sha256").read_text().strip() == digest, "manifest anchor mismatch")
    for name in ("source_files_sha256", "frozen_files_sha256", "historical_files_sha256"):
        mapping = manifest[name]
        legacy.require(isinstance(mapping, dict) and mapping, "missing frozen map")
        for relative, expected in mapping.items():
            legacy.require(evidence.track(legacy.confined(evidence.repo, relative)) == expected,
                           "frozen evidence changed")
    # Load wrappers only after their registered bytes are verified; their imports cannot dispatch.
    preaudit = adapter.load_current("audit")
    preaudit.check_schedule(manifest)
    preaudit.check_source(evidence.repo, manifest)
    preaudit.check_frozen(evidence.repo, campaign, manifest, manifest_path.parent)
    preaudit.check_history(evidence.repo, manifest)
    old = evidence.json(legacy.confined(evidence.repo,
                        ".lunar/real-eval-glm-5.2-high-score-20260909/manifest.json"))
    preaudit.check_runtime(evidence.repo, campaign, old)
    started = evidence.json(campaign / "started.json")
    legacy.require(started["manifest_sha256"] == digest and started["campaign_id"] == manifest["campaign_id"]
                   and started["planned_attempts"] == 2 and started["concurrency"] == 2,
                   "campaign startup binding mismatch")
    commit = started["registration_commit"]
    legacy.require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit), "invalid registration commit")
    legacy.after(started["started_unix_seconds"], int(legacy._git(evidence.repo, "show", "-s", "--format=%ct", commit)))
    for relative, expected in manifest["frozen_files_sha256"].items():
        if relative.startswith(("specs/", "tests/")):
            raw = legacy._git(evidence.repo, "show", f"{commit}:{relative}")
            legacy.require(hashlib.sha256(raw).hexdigest() == expected,
                           "registration commit differs from frozen scripts or tests")
    for name in ("manifest.json", "prelaunch-audit.json", "dry-run.json"):
        path = manifest_path.parent / name
        raw = legacy._git(evidence.repo, "show", f"{commit}:{path.relative_to(evidence.repo).as_posix()}")
        legacy.require(raw == path.read_bytes() == (campaign / name).read_bytes(), "uncommitted launch evidence")
        evidence.track(path)
        evidence.track(campaign / name)
        if name != "manifest.json":
            report = evidence.json(path)
            legacy.require(report["passed"] is True and report["model_calls"] == 0
                           and report["manifest_sha256"] == digest, "readiness report mismatch")
    return manifest, digest, started


def no_extra_attempts(campaign, manifest, legacy):
    indexes = {slot["index"] for slot in manifest["slots"]}
    legacy.require(indexes == {1, 2}, "unexpected registered slots")
    root = campaign / "slots"
    if root.exists():
        legacy.require(root.is_dir() and not root.is_symlink(), "unsafe slots directory")
        legacy.require({p.name for p in root.iterdir()} <= {"001", "002"}, "extra slot directory")
    markers = {f"slot-{i:03d}-{phase}.json" for i in indexes for phase in ("started", "terminated")}
    legacy.require({p.name for p in campaign.glob("slot-*.json")} <= markers, "extra slot marker")
    for slot in manifest["slots"]:
        current = legacy.confined(campaign, f"slots/{slot['index']:03d}/trial/cases")
        for name in (slot["case_key"], "runs", "001", "attempts", "001"):
            if not current.exists():
                break
            legacy.require(current.is_dir() and not current.is_symlink(), "unsafe attempt hierarchy")
            allowed = {name, "record.json", "record.previous.json"} if name == "attempts" else {name}
            legacy.require({p.name for p in current.iterdir()} <= allowed, "extra case, run or attempt")
            current = legacy.confined(current, name)


def completion(campaign, digest, summary, endings, evidence, require_complete, legacy):
    legacy.require(set(endings) == {1, 2}, "unexpected completion slots")
    path, saved = campaign / "terminated.json", campaign / "summary.json"
    ended = evidence.json(path) if path.exists() else None
    if ended:
        legacy.require(ended["manifest_sha256"] == digest and all(endings.values()), "premature termination")
        legacy.require(ended["slots"] == [evidence.json(campaign / f"slot-{index:03d}-terminated.json")
                                         for index in (1, 2)], "slot termination mismatch")
        legacy.after(ended["terminated_unix_seconds"], max(endings.values()))
    if saved.exists():
        legacy.require(ended is not None and evidence.json(saved) == summary, "saved summary mismatch")
    complete = ended is not None and saved.is_file() and summary["all_slots_terminated"] is True
    legacy.require(not require_complete or complete, "campaign incomplete; final acceptance refused")
    return complete


def audit_registered_campaign(manifest_path, campaign_path, *, require_complete=False):
    adapter, legacy = dependencies()
    manifest_path, campaign = Path(manifest_path).absolute(), Path(campaign_path).absolute()
    legacy.require(manifest_path == MEASUREMENT / "manifest.json" and campaign == adapter.CAMPAIGN,
                   "wrong corrected staged campaign")
    evidence = legacy.Evidence(adapter.REPO)
    manifest, digest, started = verify_registration(manifest_path, campaign, evidence, adapter, legacy)
    legacy.verify_runtime_import(adapter.REPO)
    dispatcher, worker, prior = adapter.load_campaign(), adapter.load_worker(), adapter.load_prior_postrun()
    legacy.require(dispatcher.CAMPAIGN == campaign and dispatcher.REPO == adapter.REPO, "dispatcher root mismatch")
    no_extra_attempts(campaign, manifest, legacy)
    summary = dispatcher.summarize()
    legacy.require(summary["planned_attempts"] == 2 and len(summary["slots"]) == 2, "wrong summary denominator")
    slots, stages, endings = [], [], {}
    for slot, row in zip(manifest["slots"], summary["slots"], strict=True):
        legacy.require(all(row[key] == slot[key] for key in ("index", "arm", "budget_arm", "case_key")),
                       "summary slot identity mismatch")
        worker.verify_bindings(manifest_path, campaign, manifest, digest, slot, require_started=False)
        result, _began, ended = legacy.verify_slot(slot, campaign, manifest, digest, started, row, evidence, dispatcher)
        slots.append(result)
        stages.append(prior.stage_evidence(slot, campaign, evidence, legacy,
                                           subject_accepted=row["subject_receipt_accepted"]))
        endings[slot["index"]] = ended
    complete = completion(campaign, digest, summary, endings, evidence, require_complete, legacy)
    no_extra_attempts(campaign, manifest, legacy)
    legacy.require(dispatcher.summarize() == summary, "campaign advanced; retry read-only observation")
    evidence.unchanged()
    return {
        "schema_version": "1", "kind": "feature074_postrun_audit", "passed": True,
        "complete": complete, "final_acceptance": complete and require_complete,
        "observed_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest,
        "registration_commit": started["registration_commit"], "implementation_commit": adapter.IMPLEMENTATION,
        "summary_sha256": hashlib.sha256(legacy.canonical(summary)).hexdigest(), "summary": summary,
        "slots": slots, "stages": stages, "evidence_sha256": evidence.hashes,
        "analysis_script_sha256": legacy.sha(Path(__file__)), "model_calls": 0,
        "credentials_loaded": False, "files_written": 0,
        "timing": {"outer_end_method": "start_unix_plus_monotonic_elapsed_estimate",
                   "tolerance_seconds": legacy.TIME_TOLERANCE_SECONDS, "exact_master_duration_available": False},
        "limitations": ["one_fresh_attempt_per_case_without_concurrent_control", "process_liveness_not_probed",
                        "plan_or_build_evidence_does_not_establish_validity", "precise_master_duration_unavailable",
                        "historical_attempts_excluded", "unknown_scores_usage_and_cost_remain_null"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        adapter, _ = dependencies()
        result = audit_registered_campaign(MEASUREMENT / "manifest.json", adapter.CAMPAIGN,
                                           require_complete=args.require_complete)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"passed": False, "error": "unavailable or inconsistent evidence", "model_calls": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
