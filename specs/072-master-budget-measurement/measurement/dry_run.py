"""Read-only registration audit and isolated deterministic workflow/worker checks.

The subprocess executes only named offline tests. It receives no inherited provider configuration,
cannot open CC Switch files or create network connections, and writes test artifacts to a temporary
directory only. No real subject, exact private harness, or campaign launch marker is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
TEST_MODULES = tuple(path.relative_to(REPO).as_posix()
                     for path in sorted((REPO / "tests").rglob("*.py"))) + (
    "specs/072-master-budget-measurement/postrun/test_audit.py",
)
SCENARIOS = {
    "budget_groups_private_bindings_and_unstarted_registration": (
        "tests/test_measurement072_audit.py",
    ),
    "budget_group_runner_wave_barrier_and_no_replacement": (
        "tests/test_measurement072_runner.py",
    ),
    "both_registered_master_limits_and_native_handoff": (
        "tests/test_measurement072_stages.py",
    ),
    "postrun_null_aware_evidence_and_completion": (
        "specs/072-master-budget-measurement/postrun/test_audit.py",
    ),
    "staged_cli_and_shared_budget_state_machine": (
        "tests/test_staged_cli.py", "tests/test_staged_workflow.py", "tests/test_staged_agent_loop.py",
    ),
    "staged_adapter_and_native_trial_success_with_one_resume": (
        "tests/test_dry_run069.py::test_native_offline_scenario[staged_success]",
    ),
    "missing_usage_retains_candidate_without_receipt_or_harness": (
        "tests/test_dry_run069.py::test_native_offline_scenario[missing_usage]",
    ),
    "timeout_retains_candidate_without_receipt_or_harness": (
        "tests/test_dry_run069.py::test_native_offline_scenario[timeout]",
    ),
    "worker_native_receipt_gate_and_independent_phase_timeouts": tuple(
        "tests/test_worker069.py::test_native_runner_owns_receipt_gate_and_phase_timeouts[" + case + "]"
        for case in ("None", "subject_process", "missing_receipt", "changed_request_pin")
    ),
    "worker_independent_environments": (
        "tests/test_worker069.py::test_environment_split_checks_endpoints_and_ignores_ambient_values",
    ),
    "worker_exclusive_markers_and_path_confinement": (
        "tests/test_worker069.py::test_control_files_never_overwrite_or_follow_links",
    ),
    "campaign_summary_schedule_launch_and_local_process_cleanup": (
        "tests/test_campaign069.py",
    ),
}
NODES = tuple(dict.fromkeys(node for nodes in SCENARIOS.values() for node in nodes))
BOOTSTRAP = '''import os, sys
def offline_guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
        raise RuntimeError("offline_test_external_operation_rejected")
    if event in {"open", "os.listdir", "os.scandir", "sqlite3.connect"} and args:
        path = os.fsdecode(args[0]) if isinstance(args[0], (str, bytes, os.PathLike)) else ""
        if ".cc-switch" in path.split(os.sep):
            raise RuntimeError("offline_test_provider_configuration_rejected")
sys.addaudithook(offline_guard)
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
'''


class DryRunError(ValueError):
    """Bounded offline failure; never includes test stdout or provider values."""


def require(condition: object) -> None:
    if not condition:
        raise DryRunError("offline_registration_or_scenario_check_failed")


def source_hashes() -> dict[str, str]:
    result = {}
    for relative in TEST_MODULES:
        path = REPO / relative
        require(path.is_file() and not path.is_symlink() and path.resolve() == path)
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_test_pins(manifest: dict, tests: dict[str, str]) -> None:
    frozen = manifest["frozen_files_sha256"]
    require(all(frozen.get(relative) == digest for relative, digest in tests.items()))


def audit_registration(manifest_path: Path, campaign_path: Path) -> dict:
    path = HERE / "audit.py"
    require(path.is_file() and not path.is_symlink())
    module = ModuleType("measurement072_dry_run_audit")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102 - trusted local auditor
    return module.audit(manifest_path, campaign_path)


def parse_results(path: Path) -> dict[str, dict]:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 1024 * 1024)
    root = ElementTree.parse(path).getroot()
    expected = {(Path(node.split("::", 1)[0]).stem, node.split("::", 1)[1])
                for node in NODES if "::" in node}
    complete_modules = {Path(node).stem for node in NODES if "::" not in node}
    actual = set()
    for case in root.iter("testcase"):
        key = (case.attrib.get("classname", "").split(".")[-1], case.attrib.get("name", ""))
        require((key in expected or (key[0] in complete_modules and bool(key[1]))) and key not in actual)
        require(not any(case.find(name) is not None for name in ("failure", "error", "skipped")))
        actual.add(key)
    require(expected <= actual and {key[0] for key in actual} >= complete_modules)
    scenarios = {}
    for name, nodes in SCENARIOS.items():
        verified = []
        for node in nodes:
            if "::" in node:
                verified.append(node)
            else:
                verified.extend(node + "::" + test_name for module, test_name in sorted(actual)
                                if module == Path(node).stem)
        scenarios[name] = {"status": "passed", "test_nodes": verified}
    return scenarios


def run_scenarios() -> dict:
    """Execute the named deterministic checks without reading or writing a campaign."""
    before = source_hashes()
    with tempfile.TemporaryDirectory(prefix="lunar-072-offline-") as temporary:
        root = Path(temporary).resolve()
        report = root / "results.xml"
        environment = {
            "PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "TMPDIR": str(root),
        }
        command = (
            str(REPO / ".venv/bin/python"), "-I", "-B", "-c", BOOTSTRAP,
            "-o", "addopts=", "-q", "-p", "no:cacheprovider", "--basetemp", str(root / "fixtures"),
            "--junitxml", str(report), *NODES,
        )
        # Selected fixtures only use in-process deterministic models and fake harness receipts.
        with tempfile.TemporaryFile() as log:
            result = subprocess.run(
                command, cwd=REPO, env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, timeout=60, check=False,
            )
            require(result.returncode == 0)
        scenarios = parse_results(report)
    require(source_hashes() == before)
    return {
        "scenarios": scenarios,
        "tests_passed": len({node for value in scenarios.values() for node in value["test_nodes"]}),
        "test_files_sha256": before,
        "isolation": {
            "inherited_environment": False, "temporary_fixture_workspaces": True,
            "network_connections_blocked": True, "ccswitch_file_access_blocked": True,
            "private_harness_executed": False,
        },
    }


def dry_run(manifest_path: Path, campaign_path: Path) -> dict:
    manifest_path, campaign_path = Path(manifest_path).absolute(), Path(campaign_path).absolute()
    audited = audit_registration(manifest_path, campaign_path)
    require(audited["status"] == "passed" and audited["model_calls"] == 0)
    manifest = json.loads(manifest_path.read_bytes())
    tests = source_hashes()
    verify_test_pins(manifest, tests)
    result = run_scenarios()
    require(result["test_files_sha256"] == tests)
    require(hashlib.sha256(manifest_path.read_bytes()).hexdigest() == audited["manifest_sha256"])
    # The second audit also verifies that no real campaign start/slot artifacts were created.
    after = audit_registration(manifest_path, campaign_path)
    require(after["status"] == "passed" and after["manifest_sha256"] == audited["manifest_sha256"])
    return {
        "schema_version": "1", "kind": "feature072_offline_dry_run", "status": "passed",
        "passed": True, "model_calls": 0, "credentials_loaded": False,
        "manifest_sha256": audited["manifest_sha256"], **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    try:
        result = dry_run(args.manifest, args.campaign)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "model_calls": 0, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
