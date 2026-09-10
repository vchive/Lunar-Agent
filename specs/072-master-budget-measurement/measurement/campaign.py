"""Fixed four-slot budget comparison, using the pinned native worker and receipt reader."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import time

from adapter import CAMPAIGN, HERE, REPO, load_legacy
from worker import HARNESS_ENV_NAMES, SUBJECT_ENV_NAMES, commands, confined, select_slot

from famou.effect_trial import EffectTrialConfig, EffectTrialRunner

__all__ = ["CAMPAIGN", "HARNESS_ENV_NAMES", "HERE", "REPO", "SUBJECT_ENV_NAMES", "EffectTrialConfig",
           "EffectTrialRunner", "commands", "launch", "read_accepted_run", "summarize"]

native = load_legacy("campaign", overrides={
    "CAMPAIGN": CAMPAIGN, "HERE": HERE, "REPO": REPO, "commands": commands,
})
BASE_ENV = native.BASE_ENV
read, require, sha, write_new = native.read, native.require, native.sha, native.write_new
execute_slot, run_slot, execute_waves = native.execute_slot, native.run_slot, native.execute_waves
read_accepted_run = native.read_accepted_run


def summarize():
    """Project native accepted records; treatment labels never confer receipt or score authority."""
    manifest = read(HERE / "manifest.json")
    manifest_sha = sha(HERE / "manifest.json")
    require(manifest_sha == (HERE / "manifest.sha256").read_text().strip())
    require((CAMPAIGN / "manifest.json").read_bytes() == (HERE / "manifest.json").read_bytes())
    select_slot(manifest, 1)
    rows = []
    for slot in manifest["slots"]:
        root = confined(CAMPAIGN, f"slots/{slot['index']:03d}")
        row = {key: slot[key] for key in ("index", "arm", "budget_arm", "case_key")}
        row.update(status="not_started", started=False, process_terminated=False,
                   subject_receipt_accepted=False, harness_receipt_accepted=False,
                   validity_score=None, overall_score=None, quality_score=None,
                   usage=None, cost_micros=None, interaction_turns=None, report_sha256=None,
                   resume_used=None, elapsed_ms=None, extraction_status=None, error_code=None)
        for phase in ("started", "terminated"):
            path = confined(CAMPAIGN, f"slot-{slot['index']:03d}-{phase}.json")
            if path.is_file():
                marker = read(path)
                require(marker["index"] == slot["index"] and marker["manifest_sha256"] == manifest_sha)
                row["started" if phase == "started" else "process_terminated"] = True
        if row["started"]:
            row["status"] = "started_unresolved"
        if row["process_terminated"]:
            require(row["started"], "terminated slot lacks start evidence")
            row["status"] = "terminated_without_accepted_report"
        if (root / "worker-terminated.json").is_file() and (root / "outcome.json").is_file():
            outcome = read(root / "outcome.json")
            if outcome.get("report_sha256") is not None:
                require(row["started"], "accepted record lacks outer start evidence")
                run, root, outcome = read_accepted_run(manifest, slot, manifest_sha)
                if row["process_terminated"]:
                    ended = read(CAMPAIGN / f"slot-{slot['index']:03d}-terminated.json")
                    require(ended["exit_code"] == outcome["worker_returncode"] and ended["failure"] is None)
                row.update(status=run["status"], report_sha256=outcome["report_sha256"],
                           record_sha256=outcome["record_sha256"], elapsed_ms=run["elapsed_ms"])
                harness_start = confined(root, "harness-started.json")
                if harness_start.is_file():
                    marker = read(harness_start)
                    require(marker["index"] == slot["index"] and marker["manifest_sha256"] == manifest_sha
                            and marker["stage"] == "harness")
                    row["subject_receipt_accepted"] = True
                row["harness_receipt_accepted"] = run["ready"]
                if run["ready"]:
                    require(row["subject_receipt_accepted"], "ready run lacks native harness dispatch")
                    for key in ("usage", "cost_micros", "interaction_turns"):
                        row[key] = run[key]
                    if run["extraction_status"] == "completed":
                        for key in ("validity_score", "overall_score", "quality_score"):
                            row[key] = run[key]
                row["extraction_status"], row["error_code"] = run["extraction_status"], run["error_code"]
                workflow = confined(root, "trial/" + run["attempt"] + "/subject/workflow/state.json")
                if workflow.is_file():
                    row["workflow_state_sha256"] = sha(workflow)
                    row["resume_used"] = read(workflow).get("resume_used")
        rows.append(row)
    groups = {}
    for arm in ("master_300", "master_1200"):
        selected = [row for row in rows if row["budget_arm"] == arm]
        require(len(selected) == 2)
        valid = sum(row["harness_receipt_accepted"] and row["validity_score"] is not None
                    and row["validity_score"] > 0 and row["overall_score"] is not None for row in selected)
        groups[arm] = {
            "planned": 2, "started": sum(row["started"] for row in selected),
            "terminated": sum(row["process_terminated"] for row in selected),
            "valid": valid, "valid_solution_rate": valid / 2,
            "subject_receipts": sum(row["subject_receipt_accepted"] for row in selected),
            "accepted_harness_receipts": sum(row["harness_receipt_accepted"] for row in selected),
        }
    return {
        "schema_version": "1", "kind": "master_budget_measurement", "manifest_sha256": manifest_sha,
        "planned_attempts": 4, "all_slots_terminated": all(row["process_terminated"] for row in rows),
        "slots": rows, "budget_arms": groups, "pooled_quality_mean": None,
        "conclusion_eligibility": "descriptive_only",
    }


def launch():
    from audit import audit
    manifest_path = HERE / "manifest.json"
    manifest = read(manifest_path)
    require(audit(manifest_path, CAMPAIGN)["passed"] is True)
    manifest_sha = sha(manifest_path)
    for name in ("manifest.json", "prelaunch-audit.json", "dry-run.json"):
        path = HERE / name
        committed = subprocess.check_output(
            ["git", "show", f"HEAD:{path.relative_to(REPO).as_posix()}"], cwd=REPO,
        )
        require(committed == path.read_bytes(), "commit the final registration/audit/dry-run first")
        require((CAMPAIGN / name).read_bytes() == committed, "mirror the committed readiness reports first")
    for relative in manifest["frozen_files_sha256"]:
        if relative.startswith(("specs/", "tests/")):
            committed = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=REPO)
            require(committed == (REPO / relative).read_bytes(), "commit the frozen scripts and tests first")
    audited, dry = read(HERE / "prelaunch-audit.json"), read(HERE / "dry-run.json")
    require(audited["manifest_sha256"] == manifest_sha and audited["passed"] is True)
    require(dry["manifest_sha256"] == manifest_sha and dry["passed"] is True and dry["model_calls"] == 0)
    # Exclusive ownership is acquired before credentials are loaded. A setup failure preserves
    # this start marker and cannot silently turn a later invocation into a replacement attempt.
    write_new(CAMPAIGN / "started.json", {
        "campaign_id": manifest["campaign_id"], "manifest_sha256": manifest_sha,
        "registration_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True,
        ).strip(),
        "started_unix_seconds": time.time(), "planned_attempts": 4, "concurrency": 2,
    })
    loader = REPO / ".lunar/real-eval-20260908/ccswitch.py"
    spec = importlib.util.spec_from_file_location("measurement072_ccswitch", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    configured = module.load_environment()
    require(configured["ANTHROPIC_MODEL"] == "glm-5.2")
    for name, digest in manifest["endpoints"].items():
        require(hashlib.sha256(configured[name].encode()).hexdigest() == digest, "provider endpoint changed")
    allowed = (*SUBJECT_ENV_NAMES, *HARNESS_ENV_NAMES)
    require(all(isinstance(configured.get(name), str) and configured[name] for name in allowed))
    environment = {**BASE_ENV, **{name: configured[name] for name in allowed}}
    outcomes = execute_waves(manifest, environment, manifest_sha)
    write_new(CAMPAIGN / "terminated.json", {
        "manifest_sha256": manifest_sha, "terminated_unix_seconds": time.time(), "slots": outcomes,
    })
    write_new(CAMPAIGN / "summary.json", summarize())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("check-only", "dry-run", "launch", "summarize"):
        actions.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    if args.check_only:
        from audit import audit
        result = audit(HERE / "manifest.json", CAMPAIGN)
    elif args.dry_run:
        from dry_run import dry_run
        result = dry_run(HERE / "manifest.json", CAMPAIGN)
    elif args.summarize:
        result = summarize()
    else:
        launch()
        return
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - no provider-bearing exception detail
        print(json.dumps({"error": type(exc).__name__, "detail": "preserve registered attempts"}))
        raise SystemExit(2) from None
