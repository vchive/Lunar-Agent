"""Read-only acceptance analysis, plus fresh synthetic snapshots for evaluator auditing.

This module never resumes a run, executes candidate source, or invokes a model.
The only executed program is a verified frozen evaluator copied into a new audit
directory. Product evidence remains unchanged.
"""
from __future__ import annotations

import hashlib
import itertools
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from tasks import CASES, check, holdouts, optimum

from famou._benchmark_files import read_regular_file
from famou._candidate_workspace_io import DirectoryChain
from famou.algorithm import AlgorithmProblemContract
from famou.automatic_solve_bundle import validate_automatic_solve_bundle
from famou.bundle_delivery import inspect_bundle_delivery
from famou.candidate_evaluation import _format_valid
from famou.candidate_evaluation_spec import canonical_json, strict_json
from famou.evaluator_bundle import (
    EvaluatorProbe,
    ProbeFile,
    _snapshot_probe,
    load_evaluator_bundle,
)
from famou.store import Store

_OUTPUTS = ("output/result.json", "output/summary.json")
_MAX_BYTES = 256 * 1024


class ReadOnlyStore(Store):
    """Use existing Store projections without its writable connection setup."""

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            yield connection
        finally:
            connection.close()


def _json(path, maximum=_MAX_BYTES):
    return strict_json(read_regular_file(path, maximum), maximum=maximum)


def _error(exc):
    # Exceptions may include generated source, paths, or provider text; keep only a class label.
    return type(exc).__name__


def _final_outputs(workspace, case_key):
    values, errors = {}, []
    for relative in _OUTPUTS:
        try:
            values[relative] = _json(workspace / relative)
        except Exception as exc:  # noqa: BLE001 - every unreadable output is an invalid measurement
            errors.append(f"{relative}:{_error(exc)}")
    result = check(case_key, CASES[case_key]["inputs"], values)
    if errors:
        result = {"validity": False, "quality": None, "errors": [*errors, *result["errors"]]}
    return result


def _delivery(store, parent, contract, cli, workspace):
    if not isinstance(cli, dict) or cli.get("run_id") != parent.id:
        raise ValueError("CLI result does not identify the stored parent")
    evolution = cli.get("evolution")
    if not isinstance(evolution, dict):
        raise TypeError("CLI evolution result is missing")
    terminal = evolution.get("materialization")
    if not isinstance(terminal, dict) or terminal.get("mode") != "bundle" or terminal.get("status") != "succeeded":
        raise ValueError("CLI has no successful bundle materialization")
    terminals = [event.get("payload") for event in store.list_events(parent.id)
                 if event.get("type") == "bundle_candidate_delivered"]
    if len(terminals) != 1 or canonical_json(terminals[0]) != canonical_json(terminal):
        raise ValueError("CLI delivery differs from the durable parent event")
    child_id = terminal.get("evolution_run_id")
    child = store.get_run(child_id) if isinstance(child_id, str) else None
    if (child is None or child.status.value != "succeeded" or evolution.get("run_id") != child_id
            or Path(child.workspace) != workspace / "evolution-run"
            or terminal.get("parent_run_id") != parent.id
            or terminal.get("contract_sha256") != contract.digest()):
        raise ValueError("delivery parent, child, or contract differs")
    relative = terminal.get("delivery_path")
    if (not isinstance(relative, str) or Path(relative).is_absolute()
            or len(Path(relative).parts) != 2 or Path(relative).parts[0] != ".bundle-deliveries"
            or not Path(relative).name.startswith(".bundle-delivery-")):
        raise ValueError("delivery path is not a parent package")
    copied = inspect_bundle_delivery(workspace / relative, expected_delivery_sha256=terminal.get("delivery_sha256"))
    manifest = copied.to_dict()
    if any(terminal.get(key) != value for key, value in manifest["identity"].items()):
        raise ValueError("delivery identity differs from the selected candidate")
    for name in _OUTPUTS:
        content = read_regular_file(workspace / name, _MAX_BYTES)
        if read_regular_file(copied.delivery_path / name, _MAX_BYTES) != content:
            raise ValueError("final output differs from the selected package")
        rows = [row for row in store.list_artifacts(parent.id)
                if row.get("kind") == "output" and row.get("path") == name]
        if len(rows) != 1 or rows[0].get("size") != len(content) or rows[0].get("sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("final output differs from its artifact row")
    return sorted(name.removeprefix("source/") for name in manifest["files"]
                  if name.startswith("source/") and Path(name).suffix == ".py")


def _audit_evaluator(slot_root, case_key, contract, evaluator):
    """Audit the generated contract and harness using only declared synthetic snapshots."""
    holder = DirectoryChain(slot_root, "measurement_audit_root_invalid")
    try:
        audit_root = slot_root / "audit"
        audit_root.mkdir(mode=0o700, exist_ok=True)
        guard = DirectoryChain(audit_root, "measurement_audit_root_invalid")
        try:
            destination = Path(tempfile.mkdtemp(prefix="holdouts-", dir=audit_root))
            guard.check()
        finally:
            guard.close()
        holder.check()
    finally:
        holder.close()
    expected_input_paths = sorted(CASES[case_key]["inputs"])
    declared_input_paths = sorted(item.path for item in contract.inputs)
    declared_output_paths = sorted(item.path for item in contract.outputs)
    rows = []
    for index, item in enumerate(holdouts(case_key)):
        expected = item["expected"]
        row = {"name": item["name"], "expected_validity": expected["validity"],
               "expected_quality": expected["quality"], "outcome": None, "reported_validity": None,
               "reported_quality": None, "reported_combined_score": None, "quality_agrees": None,
               "input_sha256": hashlib.sha256(canonical_json(item["inputs"])).hexdigest()}
        if any(name not in item["inputs"] for name in declared_input_paths):
            row["outcome"] = "contract_error"
        else:
            supplied = {"data/raw/" + name: canonical_json(item["inputs"][name]).decode()
                        for name in declared_input_paths}
            supplied.update({name: canonical_json(value).decode() for name, value in item["outputs"].items()
                             if name in declared_output_paths})
            if any(not _format_valid(spec, supplied[spec.path].encode() if spec.path in supplied else None)
                   for spec in contract.outputs):
                row["outcome"] = "schema_rejected"
            else:
                snapshot = destination / f"{index:02d}"
                snapshot.mkdir(mode=0o700)
                probe = EvaluatorProbe(item["name"], None, int(expected["validity"]), tuple(
                    ProbeFile(name, content) for name, content in sorted(supplied.items())
                ))
                try:
                    report = _snapshot_probe(evaluator, probe, contract, snapshot, 5.0)
                    row.update(outcome="harness_accepted" if report.validity == 1 else "harness_rejected",
                               reported_validity=bool(report.validity), reported_quality=report.quality,
                               reported_combined_score=report.combined_score)
                    if expected["validity"] and report.validity == 1:
                        row["quality_agrees"] = report.quality == expected["quality"]
                except Exception as exc:  # noqa: BLE001 - evaluator failures are observations, never rejections
                    row.update(outcome="harness_error", error=_error(exc))
        rows.append(row)
    accepted = lambda row: row["outcome"] == "harness_accepted"
    rejected = lambda row: row["outcome"] in {"schema_rejected", "harness_rejected"}
    valid_rows = [row for row in rows if row["expected_validity"]]
    ordering = []
    for first, second in itertools.combinations(valid_rows, 2):
        if (first["input_sha256"] != second["input_sha256"]
                or first["expected_quality"] == second["expected_quality"]):
            continue
        agrees = None
        if accepted(first) and accepted(second):
            expected_difference = first["expected_quality"] - second["expected_quality"]
            observed_difference = first["reported_combined_score"] - second["reported_combined_score"]
            agrees = expected_difference * observed_difference > 0
        ordering.append({"first": first["name"], "second": second["name"], "agrees": agrees})
    return {
        "audit_path": destination.relative_to(slot_root).as_posix(), "total": len(rows),
        "expected_valid": len(valid_rows), "expected_invalid": len(rows) - len(valid_rows),
        "contract_declarations": {"inputs": declared_input_paths, "outputs": declared_output_paths,
                                  "match_task": declared_input_paths == expected_input_paths
                                  and declared_output_paths == sorted(_OUTPUTS)},
        "schema_rejections": sum(row["outcome"] == "schema_rejected" for row in rows),
        "harness_rejections": sum(row["outcome"] == "harness_rejected" for row in rows),
        "harness_errors": sum(row["outcome"] == "harness_error" for row in rows),
        "contract_errors": sum(row["outcome"] == "contract_error" for row in rows),
        "correct_accepts": sum(row["expected_validity"] and accepted(row) for row in rows),
        "correct_rejections": sum(not row["expected_validity"] and rejected(row) for row in rows),
        "false_accepts": sum(not row["expected_validity"] and accepted(row) for row in rows),
        "false_rejects": sum(row["expected_validity"] and rejected(row) for row in rows),
        "quality_agreements": sum(row["quality_agrees"] is True for row in valid_rows),
        "quality_disagreements": sum(row["quality_agrees"] is False for row in valid_rows),
        "score_order": ordering, "probes": rows,
    }


def analyze_slot(slot_root: Path, case_key: str) -> dict:
    """Inspect one finished campaign slot and audit an available verified frozen evaluator."""
    if case_key not in CASES:
        raise ValueError("unknown acceptance case")
    slot_root = Path(slot_root).absolute()
    workspace = slot_root / "workspace"
    result = {
        "schema_version": "1", "case_key": case_key, "product_status": None,
        "product_success": False, "preparation_verified": None, "delivery_verified": False,
        "source_python_files": [], "source_python_count": 0, "source_file_requirement": False,
        "output_check": _final_outputs(workspace, case_key), "optimum": optimum(case_key, CASES[case_key]["inputs"]),
        "quality": None, "quality_gap": None, "primary_valid_completion": False,
        "evaluator_audit": None, "evaluator_audit_unavailable": None, "errors": [],
        "limitations": ["One delivered solution per slot; no candidate or model is rerun.",
                        "output_check is provisional; failed slots have null official quality and gap.",
                        "Source requirement counts Python files; it does not prove helper imports.",
                        "Synthetic holdouts audit the generated contract and evaluator, not general task coverage."],
    }
    try:
        cli = _json(slot_root / "cli.json", 4 * 1024 * 1024)
        if not isinstance(cli, dict):
            raise TypeError("CLI payload is not an object")
        result["product_status"] = cli.get("status")
    except Exception as exc:  # noqa: BLE001 - incomplete slots must still produce an analysis record
        cli = None
        result["errors"].append("cli_unavailable:" + _error(exc))
    try:
        store = ReadOnlyStore(slot_root / "home/state.db")
        held = DirectoryChain(workspace, "measurement_workspace_invalid")
        try:
            parent = store.get_run_by_workspace(workspace)
            held.check()
        finally:
            held.close()
        if parent is None:
            raise ValueError("parent run is missing")
        plan = store.get_current_plan(parent.id)
        if plan is None or plan.algorithm_problem is None:
            raise ValueError("compiled contract is missing")
        contract = AlgorithmProblemContract.from_dict(plan.algorithm_problem)
        result["parent_run_id"] = parent.id
        result["product_success"] = (isinstance(cli, dict) and cli.get("status") == "succeeded"
                                     and isinstance(cli.get("evolution"), dict)
                                     and cli["evolution"].get("status") == "succeeded"
                                     and parent.status.value == "succeeded")
        prepared = any(event.get("type") == "bundle_profile_prepared" for event in store.list_events(parent.id))
        if prepared:
            result["preparation_verified"] = False
            validate_automatic_solve_bundle(store, parent.id)
            result["preparation_verified"] = True
        if result["product_success"]:
            try:
                if not prepared:
                    raise ValueError("successful automatic run lacks preparation")
                sources = _delivery(store, parent, contract, cli, workspace)
                result.update(delivery_verified=True, source_python_files=sources, source_python_count=len(sources),
                              source_file_requirement=len(sources) >= 2)
            except Exception as exc:  # noqa: BLE001 - a failed integrity check is a measured delivery failure
                result["errors"].append("delivery_unverified:" + _error(exc))
        frozen = workspace / "evaluator-bundle"
        if frozen.exists() or frozen.is_symlink():
            try:
                bundle = load_evaluator_bundle(frozen, contract, timeout=5.0, invocation="snapshot")
                audit = _audit_evaluator(slot_root, case_key, contract, bundle.root / "evaluator.py")
                after = load_evaluator_bundle(frozen, contract, timeout=5.0, invocation="snapshot")
                if after.fingerprint != bundle.fingerprint:
                    raise ValueError("frozen evaluator changed during holdout auditing")
                result["evaluator_audit"] = audit
            except Exception as exc:  # noqa: BLE001 - invalid authority cannot provide an audit score
                result["evaluator_audit_unavailable"] = "frozen_evaluator_invalid:" + _error(exc)
        else:
            result["evaluator_audit_unavailable"] = "no_frozen_evaluator"
    except Exception as exc:  # noqa: BLE001 - failed or partial product runs remain reportable
        result["errors"].append("run_evidence_unavailable:" + _error(exc))
        result["evaluator_audit_unavailable"] = "run_evidence_unavailable"
    result["primary_valid_completion"] = bool(
        result["product_success"] and result["delivery_verified"] and result["output_check"]["validity"]
        and result["source_file_requirement"]
    )
    if result["primary_valid_completion"]:
        result["quality"] = result["output_check"]["quality"]
        result["quality_gap"] = result["optimum"] - result["quality"]
    return result
