"""Fixed synthetic contract and holdouts for the one-attempt 123 diagnostic.

The holdout executor uses only the native frozen snapshot evaluator. It does not
compile, repair, invoke a model, run a candidate, or create evaluation receipts.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from famou.algorithm import AlgorithmProblemContract
from famou.data_profile import build_private_input_profile
from famou.evaluator_bundle import (
    EvaluatorBundleError,
    EvaluatorProbe,
    FrozenEvaluatorBundle,
    ProbeFile,
    _snapshot_probe,
    load_evaluator_bundle,
)
from famou.evolution import CandidateInputArtifact

INPUT_BYTES = b'{"limit":3}\n'
INPUT_PATH = "data/raw/limit.json"
CONSTRAINT_ID = "valid-value"


def contract() -> AlgorithmProblemContract:
    """A single output rule with an exact, independently recomputed score."""
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1",
        "problem_id": "small-evaluator-diagnostic-123",
        "problem_type": "continuous",
        "statement": (
            "Read the nonnegative JSON integer limit from limit.json. The required output "
            "output/result.json is a JSON object containing value. A valid value is a JSON "
            "integer, excluding booleans and floats, with 0 <= value <= limit. Maximize value. "
            "The evaluator must independently read both files and recompute the result: "
            "validity=1, quality=value, and combined_score=value for valid outputs; "
            "otherwise validity=0, quality=null, combined_score=0, and an error_info entry "
            "with code valid-value. There are no source or execution constraints."
        ),
        "inputs": [{
            "path": "limit.json", "format": "json",
            "fields": {"limit": "A nonnegative JSON integer, excluding booleans and floats."},
        }],
        "decision_variables": ["The integer value in output/result.json."],
        "objective": {"name": "Independently read value", "direction": "maximize"},
        "hard_constraints": [{
            "id": CONSTRAINT_ID,
            "description": (
                "The output value must have Python type(value) is int after JSON parsing "
                "and satisfy 0 <= value <= the independently read input limit. "
                "Report error_info code valid-value for a violation."
            ),
            "source": "explicit_assumption", "verification": "independent",
            "verification_scope": "output", "result_fields": ["value"],
        }],
        "soft_constraints": [],
        "success_criteria": [
            "Verify the value bound and type independently and use value as the exact valid score."
        ],
        "deliverables": ["output/result.json"],
        "outputs": [{
            "path": "output/result.json", "format": "json", "fields": ["value"],
            "required": True, "description": "A JSON object with the integer decision value.",
        }],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def _no_symlink(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("diagnostic workspace must not contain a symlink")


def stage_inputs(workspace: Path) -> tuple[tuple[CandidateInputArtifact, ...], dict[str, object]]:
    """Exclusively stage registered bytes and build the native structural profile."""
    root = Path(workspace).expanduser()
    _no_symlink(root)
    target = root / INPUT_PATH
    _no_symlink(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(INPUT_BYTES)
    target.chmod(0o600)
    inputs = (CandidateInputArtifact(
        INPUT_PATH, len(INPUT_BYTES), hashlib.sha256(INPUT_BYTES).hexdigest(),
    ),)
    return inputs, build_private_input_profile(root, contract(), inputs)


def holdouts() -> list[dict[str, object]]:
    """Return fresh, JSON-serializable definitions, including exact snapshot bytes."""
    definitions = []
    for limit, values in ((1, (-1, 0, 1, 2)), (3, (0, 2, 3, 4))):
        for value in values:
            validity = int(type(value) is int and 0 <= value <= limit)
            name = f"limit-{limit}-value-{'minus-' if value < 0 else ''}{abs(value)}"
            probe = EvaluatorProbe(
                name, None if validity else CONSTRAINT_ID, validity,
                (ProbeFile(INPUT_PATH, json.dumps({"limit": limit}, separators=(",", ":")) + "\n"),
                 ProbeFile("output/result.json", json.dumps({"value": value}, separators=(",", ":")) + "\n")),
            )
            definitions.append({
                "name": name, "limit": limit, "value": value, "probe": probe.to_dict(),
                "expected": {
                    "validity": validity, "quality": value if validity else None,
                    "combined_score": value if validity else 0,
                    "constraint_code": None if validity else CONSTRAINT_ID,
                },
            })
    return definitions


def _verify(bundle: FrozenEvaluatorBundle, problem: AlgorithmProblemContract, timeout: float) -> None:
    if not isinstance(bundle, FrozenEvaluatorBundle) or bundle.invocation != "snapshot":
        raise EvaluatorBundleError("diagnostic requires a frozen snapshot evaluator")
    verified = load_evaluator_bundle(bundle.root, problem, timeout=timeout, invocation="snapshot")
    if verified.fingerprint != bundle.fingerprint:
        raise EvaluatorBundleError("diagnostic frozen evaluator fingerprint changed")


def _error_class(exc: Exception) -> str:
    # Fixed categories only: neither exception prose nor arbitrary class names escape.
    for cls in (EvaluatorBundleError, OSError, ValueError, TypeError):
        if isinstance(exc, cls):
            return cls.__name__
    return "Exception"


def audit_holdouts(
    bundle: FrozenEvaluatorBundle,
    contract: AlgorithmProblemContract,
    workspace: Path,
    timeout: float = 5,
    continuation_guard: Callable[[], None] | None = None,
    record: Callable[[dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    """Execute each fixed holdout once in a new private root and retain safe results.

    Guard and recording failures propagate so the caller can stop its attempt. A
    failed frozen-bundle check stops further probes; a harness failure consumes
    that holdout and permits the other fixed holdouts if bundle integrity remains.
    """
    root = Path(workspace).expanduser()
    _no_symlink(root)
    if continuation_guard is not None:
        continuation_guard()
    _verify(bundle, contract, timeout)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows = []
    for definition in holdouts():
        if continuation_guard is not None:
            continuation_guard()
        row = {
            "name": definition["name"], "status": "failed", "matched": False,
            "snapshot_started": False, "observed": None, "error_class": None,
        }
        integrity_failed = False
        try:
            _verify(bundle, contract, timeout)
        except Exception as exc:  # noqa: BLE001 - preserve only a fixed failure category.
            row["error_class"] = _error_class(exc)
            integrity_failed = True
        else:
            raw = definition["probe"]
            probe = EvaluatorProbe(
                raw["name"], raw["constraint_id"], raw["expected_validity"],
                tuple(ProbeFile(item["path"], item["content"]) for item in raw["files"]),
            )
            try:
                snapshot = root / probe.name
                snapshot.mkdir(mode=0o700)
                row["snapshot_started"] = True
                report = _snapshot_probe(bundle.root / "evaluator.py", probe, contract, snapshot, timeout)
                code_present = any(item["code"] == CONSTRAINT_ID for item in report.error_info)
                observed = {
                    "validity": report.validity, "quality": report.quality,
                    "combined_score": report.combined_score,
                    "constraint_code_present": code_present,
                }
                expected = definition["expected"]
                row.update(
                    status="completed", observed=observed,
                    matched=(
                        observed["validity"] == expected["validity"]
                        and observed["quality"] == expected["quality"]
                        and observed["combined_score"] == expected["combined_score"]
                        and (expected["constraint_code"] is None or code_present)
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - generated failure prose must stay private.
                row["error_class"] = _error_class(exc)
            finally:
                try:
                    _verify(bundle, contract, timeout)
                except Exception as exc:  # noqa: BLE001 - preserve only a fixed failure category.
                    row.update(status="failed", matched=False, error_class=_error_class(exc))
                    integrity_failed = True
        rows.append(row)
        if record is not None:
            record(row)
        if continuation_guard is not None:
            continuation_guard()
        if integrity_failed:
            break
    return rows
