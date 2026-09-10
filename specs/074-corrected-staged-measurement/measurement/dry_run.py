"""Two-slot registration checks plus pinned deterministic, isolated native workflow fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from adapter import HERE, REPO, load_current, load_prior

SCENARIOS = {
    "two_slot_registration_and_actual_bytes": ("tests/test_measurement074_audit.py",),
    "two_slot_exclusive_dispatch_native_receipts_and_no_replacement": ("tests/test_measurement074_runner.py",),
    "two_slot_postrun_partial_final_and_phase_evidence": (
        "specs/074-corrected-staged-measurement/postrun/test_audit.py",
    ),
    "corrected_raw_and_fenced_master_handoff_native_gate": ("tests/test_master_plan_envelope_integration.py",),
    "staged_cli_shared_ceilings_and_cooperative_resume": (
        "tests/test_staged_cli.py", "tests/test_staged_workflow.py", "tests/test_staged_agent_loop.py",
        "tests/test_measurement072_stages.py",
    ),
    "prior_actual_input_source_and_harness_byte_validators": ("tests/test_measurement072_audit.py",),
    "subject_failure_never_authorizes_harness": (
        "tests/test_dry_run069.py::test_native_offline_scenario[missing_usage]",
        "tests/test_dry_run069.py::test_native_offline_scenario[timeout]",
    ),
}
NODES = tuple(dict.fromkeys(node for nodes in SCENARIOS.values() for node in nodes))
TEST_MODULES = tuple(path.relative_to(REPO).as_posix() for path in sorted((REPO / "tests").rglob("*.py"))) + (
    "specs/074-corrected-staged-measurement/postrun/test_audit.py",
)
native = load_prior("dry_run", overrides={"HERE": HERE, "REPO": REPO, "SCENARIOS": SCENARIOS,
                                          "NODES": NODES, "TEST_MODULES": TEST_MODULES})
DryRunError, require = native.DryRunError, native.require
source_hashes, verify_test_pins, parse_results = native.source_hashes, native.verify_test_pins, native.parse_results
run_scenarios = native.run_scenarios


def audit_registration(manifest_path, campaign_path):
    return load_current("audit").audit(manifest_path, campaign_path)


def dry_run(manifest_path, campaign_path):
    manifest_path, campaign_path = Path(manifest_path).absolute(), Path(campaign_path).absolute()
    audited = audit_registration(manifest_path, campaign_path)
    require(audited["passed"] is True and audited["model_calls"] == 0)
    manifest = json.loads(manifest_path.read_bytes())
    tests = source_hashes()
    verify_test_pins(manifest, tests)
    result = run_scenarios()
    require(result["test_files_sha256"] == tests
            and hashlib.sha256(manifest_path.read_bytes()).hexdigest() == audited["manifest_sha256"])
    after = audit_registration(manifest_path, campaign_path)
    require(after["passed"] is True and after["manifest_sha256"] == audited["manifest_sha256"])
    return {"schema_version": "1", "kind": "feature074_offline_dry_run", "status": "passed", "passed": True,
            "model_calls": 0, "credentials_loaded": False, "manifest_sha256": audited["manifest_sha256"], **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    try:
        result = dry_run(args.manifest, args.campaign)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "model_calls": 0, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
