"""Read-only Feature 082 audit through the pinned, explicitly rebound two-slot validator."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
MEASUREMENT = HERE.parent / "measurement"


def load_file(name, path):
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


_adapter = load_file("postrun082_adapter", MEASUREMENT / "adapter.py")
verify_registration = _adapter.load_previous_postrun().verify_registration


def dependencies():
    adapter = load_file("postrun082_current_adapter", MEASUREMENT / "adapter.py")
    return adapter, adapter.load_legacy("postrun")


def terminal_diagnostic(slot, campaign, manifest, digest, row, evidence, reader, legacy):
    """Project bounded native diagnostics only after the accepted native failed record.

    Absence or invalid diagnostic content is advisory. The legacy evidence path and
    observation-stability gates remain strict, including for a rejected diagnostic.
    """
    result = {"status": "unavailable", "payload": None, "evidence_sha256": {}}
    if (not row["process_terminated"] or row["report_sha256"] is None
            or row["subject_receipt_accepted"] or row["harness_receipt_accepted"]):
        return result
    run, root, _outcome = reader.read_accepted_run(manifest, slot, digest)
    if run["status"] != "failed" or run["ready"] is not False:
        return result
    expected_root = legacy.confined(campaign, f"slots/{slot['index']:03d}")
    expected_attempt = f"cases/{slot['case_key']}/runs/001/attempts/001"
    legacy.require(root == expected_root and run["attempt"] == expected_attempt,
                   "native failure attempt mismatch")
    attempt = legacy.confined(root, "trial/" + expected_attempt)
    paths = [legacy.confined(attempt, relative) for relative in (
        "subject/receipt.failure.json", "diagnostics/subject-failure.json", "subject/request.json",
    )]
    paths.append(legacy.confined(root, f"trial/cases/{slot['case_key']}/runs/001/record.json"))
    for path in paths:
        if path.exists():
            result["evidence_sha256"][path.relative_to(evidence.repo).as_posix()] = evidence.track(path)
    if not all(path.exists() for path in paths):
        return result
    from famou.subject_diagnostics import normalize_diagnostic, read_bounded_file

    # Do not use a general-purpose exception renderer or read candidate/transcript content.
    raw = []
    for path, maximum in zip(paths[:3], (4096, 4096, 2 * 1024 * 1024), strict=True):
        try:
            content = read_bounded_file(attempt, path.relative_to(attempt).as_posix(), maximum)
        except (OSError, ValueError):
            result["status"] = "rejected"
            return result
        # Even malformed JSON is an observation: compare bytes before tolerant parsing.
        legacy.require(hashlib.sha256(content).hexdigest()
                       == result["evidence_sha256"][path.relative_to(evidence.repo).as_posix()],
                       "evidence changed during observation")
        raw.append(content)
    try:
        payload, collected = [normalize_diagnostic(json.loads(item)) for item in raw[:2]]
        request = json.loads(raw[2])
        valid = (payload == collected and payload["request_sha256"] == slot["request_sha256"]
                 == result["evidence_sha256"][paths[2].relative_to(evidence.repo).as_posix()]
                 and payload["mode"] == request["mode"] == "normal"
                 and payload["run_index"] == request["run_index"] == 1
                 and type(request["run_index"]) is int
                 and payload["round_index"] is request.get("round_index") is None
                 and request["receipt_path"] == "receipt.json")
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        result["status"] = "rejected"
        return result
    if not valid:
        result["status"] = "rejected"
        return result
    result.update(status="validated", payload=payload)
    return result


def audit_registered_campaign(manifest_path, campaign_path, *, require_complete=False):
    # The prior module owns only validation: no controller construction, recovery or dispatch.
    # Rebind its current dependency graph and analysis identity; never use its old campaign paths.
    adapter, legacy = dependencies()
    original_verify_slot = legacy.verify_slot

    def verify_slot(slot, campaign, manifest, digest, started, row, evidence, reader):
        result, began, ended = original_verify_slot(
            slot, campaign, manifest, digest, started, row, evidence, reader,
        )
        result["terminal_diagnostic"] = terminal_diagnostic(
            slot, campaign, manifest, digest, row, evidence, reader, legacy,
        )
        return result, began, ended

    prior = _adapter.load_previous_postrun(overrides={
        "MEASUREMENT": MEASUREMENT, "dependencies": lambda: (adapter, legacy),
        "verify_registration": verify_registration, "__file__": str(Path(__file__).resolve()),
    })
    legacy.verify_slot = verify_slot
    try:
        result = prior.audit_registered_campaign(
            manifest_path, campaign_path, require_complete=require_complete,
        )
    finally:
        legacy.verify_slot = original_verify_slot
    result["kind"] = "feature082_postrun_audit"
    result["limitations"].extend([
        "terminal_diagnostics_are_advisory_and_do_not_authorize_harness_or_scores",
        "integrated_079_080_081_measurement_not_isolated_deadline_effect",
        "request_observation_is_terminal_request_only_not_exact_master_duration",
    ])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        adapter, _legacy = dependencies()
        result = audit_registered_campaign(MEASUREMENT / "manifest.json", adapter.CAMPAIGN,
                                           require_complete=args.require_complete)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"passed": False, "error": "unavailable or inconsistent evidence", "model_calls": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
