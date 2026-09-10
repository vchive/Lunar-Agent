"""Read-only registered budget measurement audit and conservative phase evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from famou.staged_workflow import StagedWorkflowConfig
from famou.workflow_checkpoint import AggregateUsage, WorkflowController

HERE = Path(__file__).resolve().parent
MEASUREMENT = HERE.parent / "measurement"


def load_file(name, path):
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def dependencies():
    adapter = load_file("postrun072_adapter", MEASUREMENT / "adapter.py")
    legacy = adapter.load_legacy("postrun")
    # These are isolated module constants, never a mutation of historical registration/evidence.
    legacy.IMPLEMENTATION = adapter.IMPLEMENTATION
    legacy.ORDER = [("S", key) for _, key in adapter.ORDER]
    return adapter, legacy


class ReadOnlyWorkflow:
    """Use the native pure validators with an evidence reader; never construct a controller.

    WorkflowController.__init__ can recover an orphan checkpoint. This facade deliberately has
    no transition, recovery or write methods. The borrowed methods below only validate values.
    """

    _validate_binding = WorkflowController._validate_binding
    _validate_usage = WorkflowController._validate_usage
    validate_state = WorkflowController._validate_state
    load_master = WorkflowController.load_master
    load_checkpoint = WorkflowController.load_checkpoint

    def __init__(self, manifest, workflow, evidence):
        self.manifest, self.workflow, self.evidence = manifest, workflow, evidence
        self.workspace, self.checkpoints = workflow.parent, workflow / "checkpoints"

    def _read_json(self, path):
        return self.evidence.json(path)

    def _path_record(self, relative):
        result = WorkflowController._path_record(self, relative)
        self.evidence.track(self.workspace / relative)
        return result


def stage_evidence(slot, campaign, evidence, legacy, *, subject_accepted=False):
    """A validated master record and stage progression are separate from evaluator validity."""
    root = legacy.confined(campaign, f"slots/{slot['index']:03d}/trial/cases/"
                           f"{slot['case_key']}/runs/001/attempts/001/subject/workflow")
    result = {"index": slot["index"], "budget_arm": slot["budget_arm"],
              "master_duration_seconds": None, "plan_record_valid": False,
              "build_entered_observed": False, "build_transcript_present": False,
              "workflow_stage": None, "resume_used": None, "master_record_sha256": None}
    if not root.exists():
        legacy.require(not subject_accepted, "accepted staged subject lacks workflow evidence")
        return result
    legacy.require(root.is_dir() and not root.is_symlink(), "invalid workflow directory")
    config_path = legacy.confined(root, "config.json")
    state_path = legacy.confined(root, "state.json")
    master_path = legacy.confined(root, "master.json")
    transcript = legacy.confined(root, "session-transcript.jsonl")
    if not config_path.exists():
        legacy.require(not subject_accepted, "accepted staged subject lacks config")
        legacy.require(not master_path.exists() and not transcript.exists(), "phase evidence lacks config")
        return result  # Initial controller construction can precede config persistence.
    config = StagedWorkflowConfig.from_dict(evidence.json(config_path))
    legacy.require(config.to_dict() == slot["workflow_config"], "workflow config differs from registration")
    reader = ReadOnlyWorkflow(config.manifest, root, evidence)
    state = evidence.json(state_path)
    reader.validate_state(state)
    result.update(workflow_stage=state["stage"], resume_used=state["resume_used"])
    if master_path.exists():
        master = reader.load_master()
        paths = master["expected_paths"]
        legacy.require("_agent_summary.md" in paths and all(
            p.split("/")[0] not in {"case", "workflow"} and p not in {"request.json", "receipt.json"}
            for p in paths), "master paths violate staged handoff contract")
        result.update(plan_record_valid=True, master_record_sha256=evidence.track(master_path))
    later = state["stage"] in {"build_running", "checkpointed", "resuming", "build_ready",
                               "harness_pending", "terminal"}
    if state["stage"] == "master_ready" or later:
        legacy.require(result["plan_record_valid"], "stage progression lacks valid master plan")
    if transcript.exists():
        evidence.track(transcript)
        legacy.require(result["plan_record_valid"] and later, "Build transcript lacks plan/stage handoff")
        result["build_transcript_present"] = True
    result["build_entered_observed"] = later and result["plan_record_valid"]
    number = state["checkpoint_number"]
    if state["resume_used"]:
        legacy.require(number in (1, 2) and result["build_entered_observed"], "resume lacks checkpoint/stage")
    if number is not None:
        legacy.require(type(number) is int and number in (1, 2) and (number == 1 or state["resume_used"]),
                       "unexpected checkpoint count")
        previous_usage = None
        for index in range(1, number + 1):
            path = legacy.confined(root, f"checkpoints/{index:06d}.json")
            saved = evidence.json(path)
            reader._validate_binding(saved)
            legacy.require(set(saved) == set(config.manifest.to_dict()) | {
                "schema_version", "kind", "number", "stage", "prior_stage", "usage",
                "declared_paths", "transcript", "checkpoint_sha256"}, "checkpoint fields mismatch")
            legacy.require(saved["kind"] == "workflow_checkpoint" and saved["schema_version"] == "1"
                           and saved["number"] == index, "checkpoint identity mismatch")
            expected_stage = "build_ready" if index == number and state["stage"] == "build_ready" else "checkpointed"
            legacy.require(saved["stage"] == expected_stage and saved["prior_stage"] == "build_running",
                           "checkpoint sequence mismatch")
            legacy.require(saved["checkpoint_sha256"] == hashlib.sha256(legacy.canonical(
                {key: value for key, value in saved.items() if key != "checkpoint_sha256"})).hexdigest(),
                "checkpoint digest mismatch")
            usage = AggregateUsage.from_dict(saved["usage"])
            reader._validate_usage(usage)
            legacy.require(usage.available and (previous_usage is None or usage.monotonic_from(previous_usage)),
                           "checkpoint usage unavailable or moved backwards")
            previous_usage = usage
            # Earlier candidate bytes may change on resume; the archived transcript stays immutable.
            transcript_record = saved["transcript"]
            legacy.require(transcript_record is not None and transcript_record == reader._path_record(
                f"workflow/transcript-{index:06d}.jsonl"), "checkpoint transcript mismatch")
        legacy.require(AggregateUsage.from_dict(state["usage"]).monotonic_from(previous_usage),
                       "state usage moved backwards")
        if state["stage"] == "build_ready":
            final = reader.load_checkpoint(number)
            legacy.require(final.stage == "build_ready" and final.usage.to_dict() == state["usage"],
                           "build-ready checkpoint/state mismatch")
    if subject_accepted:
        legacy.require(result["plan_record_valid"] and result["build_entered_observed"]
                       and result["build_transcript_present"] and state["stage"] == "build_ready"
                       and number is not None, "accepted staged subject lacks completed Build evidence")
        active = reader._path_record("workflow/session-transcript.jsonl")
        legacy.require(final.transcript is not None and all(
            active[key] == final.transcript[key] for key in ("size_bytes", "sha256")),
            "accepted Build transcript differs from final checkpoint")
    return result


def audit_registered_campaign(manifest_path, campaign_path, *, require_complete=False):
    adapter, legacy = dependencies()
    manifest_path, campaign = Path(manifest_path).absolute(), Path(campaign_path).absolute()
    legacy.require(manifest_path == MEASUREMENT / "manifest.json" and campaign == adapter.CAMPAIGN,
                   "wrong registered budget campaign")
    evidence = legacy.Evidence(adapter.REPO)
    manifest, digest, started = legacy.verify_registration(manifest_path, campaign, evidence)
    # Loading follows frozen-byte verification. Import-time paths never load credentials/dispatch.
    preaudit = adapter.load_current("audit")
    preaudit.check_schedule(manifest)
    preaudit.check_frozen(adapter.REPO, campaign, manifest, manifest_path.parent)
    preaudit.check_history(adapter.REPO, manifest)
    legacy.verify_runtime_import(adapter.REPO)
    dispatcher, worker = adapter.load_campaign(), adapter.load_worker()
    legacy.require(dispatcher.CAMPAIGN == campaign and dispatcher.REPO == adapter.REPO,
                   "dispatcher root changed")
    legacy.no_extra_attempts(campaign, manifest)
    summary = dispatcher.summarize()
    slots, stages, starts, ends = [], [], {}, {}
    for slot, row in zip(manifest["slots"], summary["slots"], strict=True):
        legacy.require(all(row[key] == slot[key] for key in ("index", "arm", "budget_arm", "case_key")),
                       "summary grouping identity changed")
        worker.verify_bindings(manifest_path, campaign, manifest, digest, slot, require_started=False)
        result, began, ended = legacy.verify_slot(
            slot, campaign, manifest, digest, started, row, evidence, dispatcher,
        )
        slots.append(result)
        stages.append(stage_evidence(slot, campaign, evidence, legacy,
                                     subject_accepted=row["subject_receipt_accepted"]))
        starts[slot["index"]], ends[slot["index"]] = began, ended
    legacy.verify_waves(starts, ends)
    complete = legacy.completion(campaign, digest, summary, ends, evidence, require_complete)
    legacy.no_extra_attempts(campaign, manifest)
    legacy.require(dispatcher.summarize() == summary, "campaign advanced; retry read-only observation")
    evidence.unchanged()
    return {
        "schema_version": "1", "kind": "feature072_postrun_audit", "passed": True,
        "complete": complete, "final_acceptance": complete and require_complete,
        "observed_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest,
        "registration_commit": started["registration_commit"],
        "implementation_commit": adapter.IMPLEMENTATION,
        "summary_sha256": hashlib.sha256(legacy.canonical(summary)).hexdigest(), "summary": summary,
        "slots": slots, "stages": stages, "evidence_sha256": evidence.hashes,
        "analysis_script_sha256": legacy.sha(Path(__file__)),
        "model_calls": 0, "credentials_loaded": False, "files_written": 0,
        "timing": {"outer_end_method": "start_unix_plus_monotonic_elapsed_estimate",
                   "tolerance_seconds": legacy.TIME_TOLERANCE_SECONDS,
                   "exact_master_duration_available": False},
        "limitations": ["partial_observations_are_not_final_acceptance", "process_liveness_not_probed",
                        "plan_or_build_evidence_does_not_establish_validity",
                        "long_arm_handoff_does_not_prove_master_needed_more_than_300_seconds",
                        "unknown_scores_complete_usage_and_cost_remain_null"],
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
