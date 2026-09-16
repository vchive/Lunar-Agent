"""Read-only acceptance analysis with the registered source requirement enforced.

The immutable Feature 113 analyzer supplies the output oracle and frozen evaluator
holdouts. This extension requires the Feature 119 contract and portable source
evidence as well: merely finding two delivered files cannot establish completion.
No candidate, compiler, agent, or model is run here.
"""
from __future__ import annotations

import builtins
import importlib.util
from functools import lru_cache
from pathlib import Path

from famou._candidate_workspace_io import DirectoryChain
from famou.algorithm import AlgorithmProblemContract
from famou.bundle_delivery import inspect_bundle_delivery
from famou.source_constraints import (
    MAX_SOURCE_CHECK_BYTES,
    parse_source_check_evidence,
    source_constraints,
    validate_source_capabilities,
)

SHARED = Path(__file__).resolve().parents[2] / "113-real-multifile-acceptance/measurement"
SOURCE_DELIVERY_PROTOCOL = "lunar-bundle-delivery-source-v1"


def _module(name, path, *, task_module=None):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    if task_module is not None:
        # The frozen analyzer imports the generic name `tasks`. Bind only that
        # module's import, leaving sys.path and any existing sys.modules entry alone.
        def scoped_import(import_name, globals=None, locals=None, fromlist=(), level=0):
            if import_name == "tasks" and level == 0:
                return task_module
            return builtins.__import__(import_name, globals, locals, fromlist, level)

        module.__dict__["__builtins__"] = {**vars(builtins), "__import__": scoped_import}
    specification.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def shared_analyzer():
    tasks = _module("_lunar120_shared_tasks", SHARED / "tasks.py")
    return _module("_lunar120_shared_analyze", SHARED / "analyze.py", task_module=tasks)


def _registered_source_contract(contract):
    validate_source_capabilities(contract)
    checks = source_constraints(contract)
    if not checks or any(
        item.source_check.kind != "python_file_count" or item.source_check.minimum != 2
        for item in checks
    ):
        raise ValueError("registered_source_requirement_missing_or_changed")
    return checks


def analyze_slot(slot_root: Path, case_key: str) -> dict:
    """Audit one finished slot, retaining null official quality for every failure."""
    legacy = shared_analyzer()
    slot_root = Path(slot_root).absolute()
    workspace = slot_root / "workspace"
    result = legacy.analyze_slot(slot_root, case_key)
    result.update(
        source_contract_requirement=False, source_evidence_verified=False,
        source_check_validity=None, source_checks=[], source_delivery_protocol=None,
        source_check_protocol=None, source_file_requirement=False,
        primary_valid_completion=False, quality=None, quality_gap=None,
    )
    result["limitations"].extend([
        ("Source completion requires the registered hard python_file_count minimum 2 contract "
        "and verified source-aware delivery evidence, not a bare delivered file count."),
        ("Lowercase .py paths, including empty files, are counted; syntax, helper imports, "
        "dependencies, input use, and algorithm usefulness are not established."),
        "Output holdouts bypass source structure and remain separate from source evidence.",
    ])
    try:
        store = legacy.ReadOnlyStore(slot_root / "home/state.db")
        held = DirectoryChain(workspace, "measurement_workspace_invalid")
        try:
            parent = store.get_run_by_workspace(workspace)
            if parent is None or parent.id != result.get("parent_run_id"):
                raise ValueError("parent_run_missing_or_changed")
            plan = store.get_current_plan(parent.id)
            if plan is None or plan.algorithm_problem is None:
                raise ValueError("compiled_contract_missing")
            contract = AlgorithmProblemContract.from_dict(plan.algorithm_problem)
            _registered_source_contract(contract)
            result["source_contract_requirement"] = True
            if result["product_success"] and result["delivery_verified"]:
                cli = legacy._json(slot_root / "cli.json", 4 * 1024 * 1024)
                # Rebind the second read to the durable parent event, child and final
                # output artifacts before reading the additional portable evidence.
                legacy._delivery(store, parent, contract, cli, workspace)
                terminal = cli["evolution"]["materialization"]
                delivery = inspect_bundle_delivery(
                    workspace / terminal["delivery_path"],
                    expected_delivery_sha256=terminal["delivery_sha256"],
                )
                manifest = delivery.to_dict()
                if manifest["protocol"] != SOURCE_DELIVERY_PROTOCOL:
                    raise ValueError("source_aware_delivery_required")
                evidence = parse_source_check_evidence(
                    legacy.read_regular_file(
                        delivery.delivery_path / "evaluation/source-checks.json", MAX_SOURCE_CHECK_BYTES,
                    ),
                    contract, bundle_sha256=manifest["identity"]["bundle_sha256"],
                )
                if evidence["validity"] is not True:
                    raise ValueError("source_check_failed")
                sources = sorted(item["path"] for item in evidence["bundle"]["files"]
                                 if item["path"].endswith(".py"))
                result.update(
                    source_evidence_verified=True, source_check_validity=True,
                    source_checks=evidence["checks"], source_check_protocol=evidence["protocol"],
                    source_delivery_protocol=manifest["protocol"], source_python_files=sources,
                    source_python_count=len(sources), source_file_requirement=True,
                )
            held.check()
        finally:
            held.close()
    except Exception as exc:  # noqa: BLE001 - incomplete or failed slots remain measurable
        result["errors"].append("source_requirement_unverified:" + type(exc).__name__)
        result.update(source_evidence_verified=False, source_file_requirement=False)
    result["primary_valid_completion"] = bool(
        result["product_success"] and result["delivery_verified"]
        and result["output_check"]["validity"] and result["source_contract_requirement"]
        and result["source_evidence_verified"] and result["source_file_requirement"]
    )
    if result["primary_valid_completion"]:
        result["quality"] = result["output_check"]["quality"]
        result["quality_gap"] = result["optimum"] - result["quality"]
    return result
