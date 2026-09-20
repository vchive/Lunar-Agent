"""Registered task, independent arithmetic and one-use evaluator holdouts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from famou.algorithm import AlgorithmProblemContract
from famou.evaluator_bundle import (
    EvaluatorBundleError,
    EvaluatorProbe,
    FrozenEvaluatorBundle,
    ProbeFile,
    _snapshot_probe,
    load_evaluator_bundle,
)
from famou.source_constraints import validate_source_capabilities

INPUT_BYTES = b'{"limit":3}\n'
INPUT_PATH = "data/raw/limit.json"
CONSTRAINT_ID = "valid-value"
SOURCE_CONSTRAINT_ID = "python-files"
GOAL = (
    "Read the single attached input limit.json, a JSON object with the single field limit, "
    "a nonnegative JSON integer excluding booleans and floats. Produce the single required "
    "structured output output/result.json, a JSON object containing the field value. The "
    "output value must be a JSON integer excluding booleans and floats (Python type(value) "
    "is int after JSON parsing) and satisfy 0 <= value <= limit. Maximize value; feasible "
    "suboptimal values are valid. Independently read both files and recompute validity=1, "
    "quality=value and combined_score=value for valid outputs. For invalid outputs use "
    "validity=0, quality=null, combined_score=0 and error_info code valid-value. "
    "Use exactly two hard constraints: valid-value with verification=independent, "
    "verification_scope=output and result_fields=[value]; python-files with "
    "verification=independent, verification_scope=source, result_fields=[] and "
    "source_check={kind: python_file_count, minimum: 2}. Deliver at least two distinct "
    "source paths ending with lowercase .py, including the entrypoint. This source check "
    "only counts paths; it does not require imports, helper use, syntax or dependencies. "
    "Use no soft constraints or execution constraints. The contract has exactly one "
    "input path limit.json, format=json, fields={limit: a nonnegative integer}; exactly "
    "one required output path output/result.json, format=json, fields=[value]; and "
    "deliverables=[output/result.json]. Use one maximize objective without metrics, "
    "and population evolution. Generate the contract and evaluator automatically."
)

REGISTRATION_ID = "registration-139-real-multifile-closure"
CAMPAIGN_ID = "campaign-139-real-multifile-closure-20260920"
ATTEMPT_ID = "attempt-001"
CAMPAIGN_ROOT = ".lunar/real-automatic-multifile-closure-20260920"
PRODUCT_COMMIT = "87d86d9bc78171e7ce772dd9069e133249b81312"
MODEL = "glm-5.2"
TASK_BYTES = GOAL.encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def expected_input_digest() -> str:
    return sha256(INPUT_BYTES)


def expected_task_digest() -> str:
    return sha256(TASK_BYTES)


def default_holdouts() -> list[dict[str, object]]:
    """Stable compact identities used by the receipt-chain fixtures."""
    rows = []
    for index, (limit, value) in enumerate(
        ((1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2), (3, 0), (3, 3)),
        start=1,
    ):
        rows.append({"index": index, "limit": limit, "expected_value": value})
    return rows


def synthetic_source() -> dict[str, str]:
    """A valid source bundle used only as digest material in offline tests."""
    return {
        "solve/main.py": "from pathlib import Path\nPath('output').mkdir(exist_ok=True)\n",
        "solve/helper.py": "def choose(limit):\n    return limit\n",
    }


def synthetic_output() -> bytes:
    return json.dumps({"value": 3}, sort_keys=True, separators=(",", ":")).encode()


def validate_generated_contract(contract: AlgorithmProblemContract) -> None:
    """Reject drift in the generated task structure without interpreting free-form prose."""
    problem = AlgorithmProblemContract.from_dict(contract.to_dict())
    validate_source_capabilities(problem)
    if (len(problem.inputs) != 1 or problem.inputs[0].path != "limit.json"
            or problem.inputs[0].format != "json" or set(problem.inputs[0].fields) != {"limit"}
            or problem.inputs[0].key is not None):
        raise ValueError("registered_input_contract_mismatch")
    if (len(problem.outputs) != 1 or problem.outputs[0].path != "output/result.json"
            or problem.outputs[0].format != "json" or problem.outputs[0].fields != ("value",)
            or problem.outputs[0].required is not True
            or problem.deliverables != ("output/result.json",)):
        raise ValueError("registered_output_contract_mismatch")
    if (problem.objective.direction != "maximize" or problem.objective.metrics
            or problem.evolution.strategy != "population" or problem.soft_constraints):
        raise ValueError("registered_objective_contract_mismatch")
    constraints = {item.id: item for item in problem.hard_constraints}
    if set(constraints) != {CONSTRAINT_ID, SOURCE_CONSTRAINT_ID}:
        raise ValueError("registered_constraint_ids_mismatch")
    output, source = constraints[CONSTRAINT_ID], constraints[SOURCE_CONSTRAINT_ID]
    if (output.verification != "independent" or output.verification_scope != "output"
            or output.result_fields != ("value",) or output.source_check is not None):
        raise ValueError("registered_output_constraint_mismatch")
    if (source.verification != "independent" or source.verification_scope != "source"
            or source.result_fields or source.source_check is None
            or source.source_check.to_dict() != {"kind": "python_file_count", "minimum": 2}):
        raise ValueError("registered_source_constraint_mismatch")


def check(value: object, limit: int = 3) -> dict[str, object]:
    valid = type(limit) is int and limit >= 0 and type(value) is int and 0 <= value <= limit
    return {"validity": valid, "quality": value if valid else None}


def independent_output(content: bytes) -> dict[str, object]:
    """Read output bytes with no evaluator or candidate execution."""
    try:
        value = json.loads(content)
    except (TypeError, ValueError, UnicodeError):
        return check(None)
    return check(value.get("value") if type(value) is dict else None)


def _no_symlink(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("holdout workspace must not contain a symlink")


def holdouts() -> list[dict[str, object]]:
    """Return fresh definitions including the exact snapshot bytes."""
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
        raise EvaluatorBundleError("holdouts require a frozen snapshot evaluator")
    verified = load_evaluator_bundle(bundle.root, problem, timeout=timeout, invocation="snapshot")
    if verified.fingerprint != bundle.fingerprint:
        raise EvaluatorBundleError("holdout frozen evaluator fingerprint changed")


def _error_class(exc: Exception) -> str:
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
    """Execute and record each registered holdout once, stopping on integrity drift."""
    validate_generated_contract(contract)
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
        except Exception as exc:  # noqa: BLE001 - generated failure prose remains private
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
                row.update(status="completed", observed=observed, matched=(
                    observed["validity"] == expected["validity"]
                    and observed["quality"] == expected["quality"]
                    and observed["combined_score"] == expected["combined_score"]
                    and (expected["constraint_code"] is None or code_present)
                ))
            except Exception as exc:  # noqa: BLE001 - generated failure prose remains private
                row["error_class"] = _error_class(exc)
            finally:
                try:
                    _verify(bundle, contract, timeout)
                except Exception as exc:  # noqa: BLE001 - generated failure prose remains private
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
