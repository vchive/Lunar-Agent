"""Read-only postrun evidence audit; an observation never repairs or overwrites a campaign."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IMPLEMENTATION = "80f5af10f4a25dab5c5aa2ad767e3b78994f34a3"
ORDER = [("M", "sheet_metal_nesting"), ("S", "china_post_pickup_optimization"),
         ("S", "sheet_metal_nesting"), ("M", "china_post_pickup_optimization")]
TIME_TOLERANCE_SECONDS = 2.0


class AuditError(ValueError):
    """A protocol mismatch, reported without provider or candidate content."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def sha(path):
    require(path.is_file() and not path.is_symlink(), "missing or linked evidence file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confined(root, relative):
    path = Path(relative)
    require(isinstance(relative, str) and relative == path.as_posix() and path.parts
            and not path.is_absolute() and ".." not in path.parts and "\\" not in relative,
            "evidence path escaped its root")
    require(not root.is_symlink(), "linked evidence root")
    current = root
    for part in path.parts:
        current = current / part
        require(not current.is_symlink(), "linked evidence path")
    return current


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024,
            "missing, linked or oversized JSON evidence")
    result = json.loads(path.read_bytes())
    require(isinstance(result, dict), "expected JSON object evidence")
    return result


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid observed time")
    return value


def after(later, earlier):
    require(finite(later) + TIME_TOLERANCE_SECONDS >= finite(earlier), "process order violated")


class Evidence:
    def __init__(self, repo):
        self.repo, self.hashes = repo, {}

    def track(self, path):
        digest = sha(path)
        key = path.relative_to(self.repo).as_posix()
        require(key not in self.hashes or self.hashes[key] == digest, "evidence changed during observation")
        self.hashes[key] = digest
        return digest

    def json(self, path):
        before = self.track(path)
        value = read(path)
        require(sha(path) == before, "evidence changed during observation")
        return value

    def unchanged(self):
        for relative, expected in self.hashes.items():
            require(sha(confined(self.repo, relative)) == expected, "evidence changed during observation")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_frozen_modules(directory):
    # Frozen modules are imported only after their bytes have been checked. Neither import loads
    # CC Switch; campaign.launch(), worker.main() and preparation.main() are never called.
    saved = {name: sys.modules.get(name) for name in ("prepare", "worker")}
    bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        prepare = _load_module("postrun069_prepare", directory / "prepare.py")
        sys.modules["prepare"] = prepare
        worker = _load_module("postrun069_worker", directory / "worker.py")
        sys.modules["worker"] = worker
        campaign = _load_module("postrun069_campaign", directory / "campaign.py")
        return campaign, worker
    finally:
        sys.dont_write_bytecode = bytecode_setting
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def _git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo, stderr=subprocess.DEVNULL)


def verify_runtime_import(repo):
    bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        import famou
    finally:
        sys.dont_write_bytecode = bytecode_setting
    require(Path(famou.__file__).resolve().parent == repo / "src/famou",
            "imported runtime differs from verified repository source")


def verify_registration(manifest_path, campaign, evidence):
    manifest = evidence.json(manifest_path)
    digest = evidence.track(manifest_path)
    require(manifest_path.read_bytes() == (campaign / "manifest.json").read_bytes(),
            "local and committed registration differ")
    evidence.track(campaign / "manifest.json")
    for directory in (manifest_path.parent, campaign):
        require((directory / "manifest.sha256").read_text().strip() == digest, "manifest anchor mismatch")
        evidence.track(directory / "manifest.sha256")
    require(manifest["implementation_commit"] == IMPLEMENTATION, "implementation commit changed")
    require(manifest["planned_attempts"] == 4 and manifest["execution"]["waves"] == [[1, 2], [3, 4]]
            and manifest["execution"]["concurrency"] == 2, "fixed schedule changed")
    require([(slot["index"], slot["arm"], slot["case_key"]) for slot in manifest["slots"]]
            == [(index, arm, key) for index, (arm, key) in enumerate(ORDER, 1)], "fixed slots changed")
    started = evidence.json(campaign / "started.json")
    require(started["manifest_sha256"] == digest and started["campaign_id"] == manifest["campaign_id"]
            and started["planned_attempts"] == 4 and started["concurrency"] == 2, "campaign start binding failed")
    commit = started["registration_commit"]
    require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit), "invalid registration commit")
    after(started["started_unix_seconds"], int(_git(evidence.repo, "show", "-s", "--format=%ct", commit)))
    for name in ("manifest.json", "prelaunch-audit.json", "dry-run.json"):
        path = manifest_path.parent / name
        raw = _git(evidence.repo, "show", f"{commit}:{path.relative_to(evidence.repo).as_posix()}")
        require(raw == path.read_bytes() == (campaign / name).read_bytes(), "registration was not committed before dispatch")
        evidence.track(path)
        evidence.track(campaign / name)
        if name != "manifest.json":
            report = read(path)
            require(report["manifest_sha256"] == digest and report["passed"] is True
                    and report["model_calls"] == 0, "prelaunch report binding failed")
    for name in ("source_files_sha256", "frozen_files_sha256", "historical_files_sha256"):
        mapping = manifest[name]
        require(isinstance(mapping, dict) and mapping, "missing frozen evidence map")
        for relative, expected in mapping.items():
            require(evidence.track(confined(evidence.repo, relative)) == expected, "frozen evidence changed")
    tracked = set(_git(evidence.repo, "ls-tree", "-r", "--name-only", IMPLEMENTATION,
                       "--", "src/famou").decode().splitlines())
    tracked = {name for name in tracked if name.endswith(".py")}
    actual = {p.relative_to(evidence.repo).as_posix() for p in (evidence.repo / "src/famou").rglob("*.py")}
    require(actual == tracked == set(manifest["source_files_sha256"]), "source file set changed")
    for relative, expected in manifest["source_files_sha256"].items():
        require(hashlib.sha256(_git(evidence.repo, "show", f"{IMPLEMENTATION}:{relative}")).hexdigest()
                == expected, "source differs from implementation git bytes")
    for name in ("prepare.py", "worker.py", "campaign.py"):
        require((manifest_path.parent / name).relative_to(evidence.repo).as_posix()
                in manifest["frozen_files_sha256"], "dispatcher was not frozen")
    return manifest, digest, started


def no_extra_attempts(campaign, manifest):
    slots = campaign / "slots"
    if slots.exists():
        require(slots.is_dir() and not slots.is_symlink(), "unsafe slots directory")
        require({p.name for p in slots.iterdir()} <= {"001", "002", "003", "004"}, "extra slot directory")
    allowed_markers = {f"slot-{index:03d}-{phase}.json" for index in range(1, 5)
                       for phase in ("started", "terminated")}
    require({p.name for p in campaign.glob("slot-*.json")} <= allowed_markers, "extra slot marker")
    for slot in manifest["slots"]:
        current = confined(campaign, f"slots/{slot['index']:03d}/trial/cases")
        for name in (slot["case_key"], "runs", "001", "attempts", "001"):
            if not current.exists():
                break
            require(current.is_dir() and not current.is_symlink(), "unsafe attempt hierarchy")
            allowed = {name, "record.json", "record.previous.json"} if name == "attempts" else {name}
            require({p.name for p in current.iterdir()} <= allowed, "extra case, run or attempt")
            current = confined(current, name)


def marker(path, index, digest, evidence, stage=None):
    if not path.exists():
        return None
    item = evidence.json(path)
    require(item["index"] == index and item["manifest_sha256"] == digest, "stage marker identity mismatch")
    if stage is not None:
        require(item["stage"] == stage, "stage marker phase mismatch")
    return item


def verify_slot(slot, campaign, manifest, digest, started, row, evidence, reader_module):
    index = slot["index"]
    root = confined(campaign, f"slots/{index:03d}")
    outer_start = marker(campaign / f"slot-{index:03d}-started.json", index, digest, evidence)
    outer_end = marker(campaign / f"slot-{index:03d}-terminated.json", index, digest, evidence)
    require(bool(outer_start) == row["started"] and bool(outer_end) == row["process_terminated"],
            "slot markers changed during summary observation")
    if outer_start is None:
        require(not root.exists() and outer_end is None, "slot materialized without dispatch")
        return {"index": index, "started": False, "terminated": False}, None, None
    after(outer_start["started_unix_seconds"], started["started_unix_seconds"])
    estimated_end = None
    if outer_end is not None:
        estimated_end = finite(outer_start["started_unix_seconds"]) + finite(outer_end["elapsed_seconds"])
    worker_start = marker(root / "worker-started.json", index, digest, evidence)
    worker_end = marker(root / "worker-terminated.json", index, digest, evidence)
    if worker_start:
        after(worker_start["started_unix_seconds"], outer_start["started_unix_seconds"])
    require(worker_end is None or worker_start is not None, "worker termination lacks startup")
    outcome = None
    if (root / "outcome.json").exists():
        outcome = evidence.json(root / "outcome.json")
        require(worker_start is not None and outcome["manifest_sha256"] == digest
                and all(outcome[key] == slot[key] for key in ("index", "arm", "case_key")), "worker outcome binding failed")
    if worker_end:
        require(outcome is not None and worker_end["outcome_sha256"] == evidence.track(root / "outcome.json")
                and worker_end["returncode"] == outcome["worker_returncode"], "worker termination digest mismatch")
        if outer_end and outer_end["failure"] is None:
            require(outer_end["exit_code"] == worker_end["returncode"], "outer and worker exits disagree")
    previous_end = worker_start["started_unix_seconds"] if worker_start else None
    phase_markers = {}
    for phase in ("subject", "harness"):
        begin = marker(root / f"{phase}-started.json", index, digest, evidence, phase)
        end = marker(root / f"{phase}-terminated.json", index, digest, evidence, phase)
        require(end is None or begin is not None, "phase termination lacks startup")
        if begin:
            require(worker_start is not None and previous_end is not None, "phase started out of order")
            after(begin["started_unix_seconds"], previous_end)
            require(begin["outer_timeout_seconds"] == manifest["execution"][phase + "_outer_seconds"],
                    "phase outer limit changed")
            phase_root = confined(root, f"trial/cases/{slot['case_key']}/runs/001/attempts/001/{phase}")
            require(evidence.track(phase_root / "request.json") == begin["request_sha256"], "phase request changed")
            if phase == "subject":
                require(begin["request_sha256"] == slot["request_sha256"], "subject request differs from registration")
                verify_public(phase_root, manifest["cases"][slot["case_key"]]["suite"], evidence)
                workflow = confined(phase_root, "workflow/config.json")
                if workflow.exists():
                    require(slot["arm"] == "S" and evidence.json(workflow) == slot["workflow_config"], "workflow configuration changed")
            else:
                subject_begin, subject_end = phase_markers["subject"]
                require(subject_begin is not None and subject_end is not None
                        and subject_end["returncode"] == 0, "harness started without successful subject process")
                suite = manifest["cases"][slot["case_key"]]["suite"]
                case = suite["cases"][0]
                require(evidence.json(phase_root / "request.json") == {
                    "schema_version": "1", "candidate_workspace": "../subject", "run_index": 1,
                    "benchmark": suite["benchmark"], "evaluation_profile": suite["evaluation_profile"],
                    "case": {key: case[key] for key in ("key", "revision_id", "digest")},
                    "harness": case["harness"], "receipt_path": "receipt.json",
                }, "harness request differs from registered identity")
        previous_end = (finite(begin["started_unix_seconds"]) + finite(end["elapsed_seconds"])) if begin and end else None
        if previous_end is not None and estimated_end is not None:
            after(estimated_end, previous_end)
        phase_markers[phase] = (begin, end)
    if row["harness_receipt_accepted"]:
        require(all(phase_markers[phase][1] and phase_markers[phase][1]["returncode"] == 0
                    for phase in ("subject", "harness")), "accepted receipts lack successful phase exits")
    if worker_end and outcome and outcome.get("report_sha256"):
        # Frozen summarize() has already validated this chain; track its authoritative bytes too.
        for relative in ("trial/report.json", "trial/control/state.json", "trial/control/suite.json",
                         "trial/control/baseline.json", f"trial/cases/{slot['case_key']}/runs/001/record.json"):
            evidence.track(confined(root, relative))
        accepted_run, _, _ = reader_module.read_accepted_run(manifest, slot, digest)
        validate_receipts(reader_module, manifest, slot, campaign, root, row, accepted_run, evidence)
    attempt = confined(root, f"trial/cases/{slot['case_key']}/runs/001/attempts/001")
    for relative in ("subject/receipt.json", "harness/receipt.json", "subject/receipt.failure.json",
                     "diagnostics/subject-failure.json", "subject/workflow/state.json"):
        path = confined(attempt, relative)
        if path.exists():
            evidence.track(path)
    return {"index": index, "started": True, "terminated": outer_end is not None,
            "accepted_native_report": row["report_sha256"] is not None,
            "subject_receipt_accepted": row["subject_receipt_accepted"],
            "harness_receipt_accepted": row["harness_receipt_accepted"]}, outer_start, estimated_end


def validate_receipts(dispatcher, manifest, slot, campaign, root, row, run, evidence):
    """Reparse accepted receipts through native validators, without invoking a process."""
    if not row["subject_receipt_accepted"]:
        return
    subject_command, harness_command = dispatcher.commands(manifest, campaign, slot)
    config = dispatcher.EffectTrialConfig(
        runs_per_case=1, timeout_seconds=5400, requested_model="glm-5.2",
        subject_command=subject_command, harness_command=harness_command,
        subject_environment=dict.fromkeys((*dispatcher.SUBJECT_ENV_NAMES, "PYTHONDONTWRITEBYTECODE"), ""),
        harness_environment=dict.fromkeys((*dispatcher.HARNESS_ENV_NAMES, "PYTHONDONTWRITEBYTECODE"), ""),
        model_profile_sha256=manifest["profile_sha256"],
        subject_model_profile_path=campaign / "inputs/profile.json",
    )

    def refuse_dispatch(*args, **kwargs):
        raise AuditError("postrun validation cannot dispatch")

    reader = dispatcher.EffectTrialRunner(
        campaign / "inputs" / f"{slot['case_key']}-suite.json",
        campaign / "inputs" / f"{slot['case_key']}-baseline.json", root / "trial",
        case_sources={slot["case_key"]: dispatcher.REPO / manifest["cases"][slot["case_key"]]["public_root_rel"]},
        config=config, resume=True, process_executor=refuse_dispatch,
    )
    attempt = confined(root, f"trial/cases/{slot['case_key']}/runs/001/attempts/001")
    subject = confined(attempt, "subject/receipt.json")
    evidence.track(subject)
    metadata = reader._subject_receipt(subject)
    if row["harness_receipt_accepted"]:
        harness = confined(attempt, "harness/receipt.json")
        evidence.track(harness)
        scored = reader._harness_receipt(harness, reader.suite.cases[0])
        require(all(run[key] == value for key, value in {**metadata, **scored}.items()),
                "accepted receipt content differs from authoritative record")


def verify_public(subject, suite, evidence):
    case = suite["cases"][0]
    public = confined(subject, "case")
    expected = {item["path"] for item in case["public_files"]}
    actual = set()
    for path in public.rglob("*"):
        require(not path.is_symlink(), "linked public projection")
        if path.is_file():
            actual.add(path.relative_to(public).as_posix())
    require(actual == expected, "public projection file set changed")
    for descriptor in case["public_files"]:
        path = confined(public, descriptor["path"])
        require(evidence.track(path) == descriptor["sha256"] and path.stat().st_size == descriptor["size"],
                "public projection bytes changed")


def verify_waves(starts, ends):
    for index in (3, 4):
        if starts[index] is not None:
            require(all(ends[prior] is not None for prior in (1, 2)), "wave two began before wave one terminated")
            after(starts[index]["started_unix_seconds"], max(ends[1], ends[2]))


def completion(campaign, manifest_sha, summary, outer_endings, evidence, require_complete):
    ended_path, summary_path = campaign / "terminated.json", campaign / "summary.json"
    ended = evidence.json(ended_path) if ended_path.exists() else None
    if ended:
        require(ended["manifest_sha256"] == manifest_sha and all(outer_endings.values()), "campaign terminated before all slots")
        require(ended["slots"] == [read(campaign / f"slot-{index:03d}-terminated.json") for index in range(1, 5)],
                "campaign termination differs from slot evidence")
        after(ended["terminated_unix_seconds"], max(outer_endings.values()))
    if summary_path.exists():
        require(ended is not None and evidence.json(summary_path) == summary, "saved final summary differs from native reconstruction")
    complete = ended is not None and summary_path.is_file() and summary["all_slots_terminated"] is True
    require(not require_complete or complete, "campaign is incomplete; final acceptance refused")
    return complete


def audit_registered_campaign(manifest_path, campaign_path, *, require_complete=False):
    """Inspect one stable snapshot. Caller may save a new report with exclusive creation only."""
    manifest_path, campaign = Path(manifest_path).absolute(), Path(campaign_path).absolute()
    repo = manifest_path.parents[3]
    require(campaign == repo / ".lunar" / "real-eval-glm-5.2-staged-20260910", "wrong campaign directory")
    evidence = Evidence(repo)
    manifest, digest, started = verify_registration(manifest_path, campaign, evidence)
    verify_runtime_import(repo)
    dispatcher, worker = _load_frozen_modules(manifest_path.parent)
    require(dispatcher.CAMPAIGN == campaign and dispatcher.REPO == repo, "dispatcher root changed")
    no_extra_attempts(campaign, manifest)
    summary = dispatcher.summarize()
    slots, starts, ends = [], {}, {}
    for slot, row in zip(manifest["slots"], summary["slots"], strict=True):
        # Includes actual private case/extractor/evaluator hashes, not merely suite declarations.
        worker.verify_bindings(manifest_path, campaign, manifest, digest, slot, require_started=False)
        result, began, ended = verify_slot(slot, campaign, manifest, digest, started, row, evidence, dispatcher)
        slots.append(result)
        starts[slot["index"]], ends[slot["index"]] = began, ended
    verify_waves(starts, ends)
    complete = completion(campaign, digest, summary, ends, evidence, require_complete)
    no_extra_attempts(campaign, manifest)
    require(dispatcher.summarize() == summary, "campaign advanced during observation; retry read-only audit")
    evidence.unchanged()
    return {
        "schema_version": "1", "kind": "feature069_postrun_audit", "passed": True,
        "analysis_script_sha256": sha(Path(__file__)),
        "complete": complete, "final_acceptance": complete and require_complete,
        "observed_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest,
        "registration_commit": started["registration_commit"], "implementation_commit": IMPLEMENTATION,
        "summary_sha256": hashlib.sha256(canonical(summary)).hexdigest(), "summary": summary,
        "slots": slots, "evidence_sha256": evidence.hashes, "model_calls": 0,
        "credentials_loaded": False, "files_written": 0,
        "timing": {"outer_end_method": "start_unix_plus_monotonic_elapsed_estimate",
                   "tolerance_seconds": TIME_TOLERANCE_SECONDS, "exact_wall_termination_known": False,
                   "tolerance_is_postrun_audit_rule_not_preregistered_budget": True},
        "limitations": ["partial_observations_are_not_final_campaign_acceptance",
                        "unknown_scores_and_usage_remain_null", "process_liveness_not_probed",
                        "public_projection_checks_are_not_an_os_sandbox"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        result = audit_registered_campaign(args.manifest, args.campaign, require_complete=args.require_complete)
    except (AuditError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"passed": False, "error": str(exc) if isinstance(exc, AuditError)
                          else "malformed or unavailable evidence", "model_calls": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
