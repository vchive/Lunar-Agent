"""Runtime-neutral contracts for algorithmic problem solving.

This module deliberately contains metadata validation and workspace materialization only. It does
not select a model, execute a solver, or run an evaluator. Those operations consume these contracts
in later features, which keeps the controller independent from Hermes/OpenCode/Codex runtimes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MAX_CONTRACT_BYTES = 64 * 1024
MAX_TEXT_BYTES = 8_000
MAX_ITEMS = 64
MAX_FIELDS = 128
MAX_METRICS = 32
MAX_REPORT_BYTES = 32 * 1024
MAX_ERROR_INFO = 32
MAX_OUTPUTS = 32
MAX_OUTPUT_FIELDS = 32
SUPPORTED_PROBLEM_TYPES = frozenset(
    {"scheduling", "routing", "packing", "assignment", "forecasting", "network_flow", "continuous"}
)
PROVENANCE_VALUES = frozenset({"user_confirmed", "data_observed", "explicit_assumption"})
VERIFICATION_VALUES = frozenset({"independent", "partial", "solver"})
EVOLUTION_STRATEGIES = frozenset({"loop", "population", "openevolve"})
OUTPUT_FORMATS = frozenset({"json", "jsonl", "csv", "text"})
_SECRET_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)"
)


def _text(value: object, field_name: str, *, required: bool = True, limit: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        if required:
            raise TypeError(f"{field_name} must be a string")
        return ""
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} exceeds {limit} bytes")
    if _SECRET_RE.search(value):
        raise ValueError(f"{field_name} contains credential-like content")
    return value


def _safe_segment(value: object, field_name: str) -> str:
    value = _text(value, field_name, limit=512)
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{field_name} must be a safe identifier")
    return value


def _relative_path(value: object, field_name: str = "input path") -> str:
    path = _text(value, field_name, limit=512)
    if "\\" in path or "\x00" in path:
        raise ValueError(f"{field_name} must be a portable relative path")
    candidate = Path(path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError(f"{field_name} must be a portable relative path")
    return path


def _strings(value: object, field_name: str, *, max_items: int = MAX_ITEMS) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"{field_name} must be a bounded string array")
    return tuple(_text(item, field_name) for item in value)


def _json_size(value: object, field_name: str, *, limit: int = MAX_CONTRACT_BYTES) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} exceeds {limit} bytes")
    if _SECRET_RE.search(encoded):
        raise ValueError(f"{field_name} contains credential-like content")


@dataclass(frozen=True)
class InputSpec:
    path: str
    format: str
    fields: dict[str, str]
    key: str | None = None

    def __post_init__(self) -> None:
        path = _relative_path(self.path)
        _text(self.format, "input format", limit=128)
        if not self.fields or len(self.fields) > MAX_FIELDS:
            raise ValueError("input fields must be a bounded non-empty object")
        normalized_fields: dict[str, str] = {}
        for name, description in self.fields.items():
            field_name = _safe_segment(name, "input field name")
            normalized_fields[field_name] = _text(description, f"input field {field_name}", limit=512)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "format", self.format.strip())
        object.__setattr__(self, "fields", normalized_fields)
        if self.key is not None:
            object.__setattr__(self, "key", _safe_segment(self.key, "input key"))
            if self.key not in normalized_fields:
                raise ValueError("input key must name a declared field")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "format": self.format, "fields": dict(self.fields), "key": self.key}

    @classmethod
    def from_dict(cls, value: object) -> InputSpec:
        if not isinstance(value, dict):
            raise TypeError("input must be an object")
        fields = value.get("fields")
        if not isinstance(fields, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in fields.items()):
            raise TypeError("input fields must be a string object")
        key = value.get("key")
        if key is not None and not isinstance(key, str):
            raise TypeError("input key must be a string or null")
        return cls(
            path=_relative_path(value.get("path")),
            format=_text(value.get("format"), "input format", limit=128),
            fields=fields,
            key=key,
        )


@dataclass(frozen=True)
class MetricSpec:
    name: str
    direction: Literal["maximize", "minimize"]
    weight: float

    def __post_init__(self) -> None:
        _text(self.name, "metric name", limit=256)
        if self.direction not in {"maximize", "minimize"}:
            raise ValueError("metric direction must be maximize or minimize")
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)) or not math.isfinite(float(self.weight)) or self.weight < 0:
            raise ValueError("metric weight must be a finite non-negative number")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "direction": self.direction, "weight": self.weight}

    @classmethod
    def from_dict(cls, value: object) -> MetricSpec:
        if not isinstance(value, dict):
            raise TypeError("objective metric must be an object")
        return cls(
            name=_text(value.get("name"), "metric name", limit=256),
            direction=value.get("direction"),  # type: ignore[arg-type]
            weight=value.get("weight", 0),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ObjectiveSpec:
    name: str
    direction: Literal["maximize", "minimize"]
    metrics: tuple[MetricSpec, ...] = ()

    def __post_init__(self) -> None:
        _text(self.name, "objective name", limit=512)
        if self.direction not in {"maximize", "minimize"}:
            raise ValueError("objective direction must be maximize or minimize")
        if len(self.metrics) > MAX_METRICS:
            raise ValueError("objective has too many metrics")
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("objective metric names must be unique")
        if self.metrics and sum(metric.weight for metric in self.metrics) <= 0:
            raise ValueError("objective metric weights must have a positive total")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "direction": self.direction}
        if self.metrics:
            result["metrics"] = [metric.to_dict() for metric in self.metrics]
        return result

    @classmethod
    def from_dict(cls, value: object) -> ObjectiveSpec:
        if not isinstance(value, dict):
            raise TypeError("objective must be an object")
        raw_metrics = value.get("metrics", [])
        if not isinstance(raw_metrics, list):
            raise TypeError("objective metrics must be an array")
        return cls(
            name=_text(value.get("name"), "objective name", limit=512),
            direction=value.get("direction"),  # type: ignore[arg-type]
            metrics=tuple(MetricSpec.from_dict(item) for item in raw_metrics),
        )


@dataclass(frozen=True)
class ConstraintSpec:
    id: str
    description: str
    source: Literal["user_confirmed", "data_observed", "explicit_assumption"]
    verification: Literal["independent", "partial", "solver"]
    result_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _safe_segment(self.id, "constraint id")
        _text(self.description, "constraint description")
        if self.source not in PROVENANCE_VALUES:
            raise ValueError("constraint source is unsupported")
        if self.verification not in VERIFICATION_VALUES:
            raise ValueError("constraint verification is unsupported")
        if len(self.result_fields) > MAX_ITEMS:
            raise ValueError("constraint result fields are too many")
        for field_name in self.result_fields:
            _safe_segment(field_name, "constraint result field")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "source": self.source,
            "verification": self.verification,
            "result_fields": list(self.result_fields),
        }

    @classmethod
    def from_dict(cls, value: object) -> ConstraintSpec:
        if not isinstance(value, dict):
            raise TypeError("constraint must be an object")
        result_fields = value.get("result_fields", [])
        if not isinstance(result_fields, list) or any(not isinstance(item, str) for item in result_fields):
            raise TypeError("constraint result_fields must be a string array")
        return cls(
            id=_safe_segment(value.get("id"), "constraint id"),
            description=_text(value.get("description"), "constraint description"),
            source=value.get("source"),  # type: ignore[arg-type]
            verification=value.get("verification"),  # type: ignore[arg-type]
            result_fields=tuple(result_fields),
        )


@dataclass(frozen=True)
class EvolutionSpec:
    strategy: Literal["loop", "population", "openevolve"] = "loop"
    max_rounds: int = 5
    stagnation_rounds: int = 3

    def __post_init__(self) -> None:
        if self.strategy not in EVOLUTION_STRATEGIES:
            raise ValueError("evolution strategy must be loop, population, or openevolve")
        for name, value, maximum in (("max_rounds", self.max_rounds, 10_000), ("stagnation_rounds", self.stagnation_rounds, 1_000)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be a positive bounded integer")

    def to_dict(self) -> dict[str, Any]:
        return {"strategy": self.strategy, "max_rounds": self.max_rounds, "stagnation_rounds": self.stagnation_rounds}

    @classmethod
    def from_dict(cls, value: object) -> EvolutionSpec:
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise TypeError("evolution must be an object")
        return cls(
            strategy=value.get("strategy", "loop"),  # type: ignore[arg-type]
            max_rounds=value.get("max_rounds", 5),  # type: ignore[arg-type]
            stagnation_rounds=value.get("stagnation_rounds", 3),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class OutputSpec:
    """A structured data file the algorithm mission is expected to produce."""

    path: str
    format: Literal["json", "jsonl", "csv", "text"]
    fields: tuple[str, ...] = ()
    required: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        path = _relative_path(self.path, "output path")
        if not path.startswith("output/") or path == "output/":
            raise ValueError("output path must be below the output/ directory")
        output_format = _text(self.format, "output format", limit=32).lower()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError("output format must be json, jsonl, csv, or text")
        if isinstance(self.required, bool) is False:
            raise TypeError("output required must be a boolean")
        if len(self.fields) > MAX_OUTPUT_FIELDS:
            raise ValueError("output fields are too many")
        normalized_fields = tuple(_safe_segment(field, "output field") for field in self.fields)
        if len(set(normalized_fields)) != len(normalized_fields):
            raise ValueError("output fields must be unique")
        if output_format == "text" and normalized_fields:
            raise ValueError("text outputs cannot declare fields")
        description = _text(self.description, "output description", required=False, limit=512)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "format", output_format)
        object.__setattr__(self, "fields", normalized_fields)
        object.__setattr__(self, "description", description)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "format": self.format,
            "fields": list(self.fields),
            "required": self.required,
        }
        if self.description:
            payload["description"] = self.description
        return payload

    @classmethod
    def from_dict(cls, value: object) -> OutputSpec:
        if not isinstance(value, dict):
            raise TypeError("output must be an object")
        unknown = set(value) - {"path", "format", "fields", "required", "description"}
        if unknown:
            raise ValueError(f"output contains unknown fields: {', '.join(sorted(unknown))}")
        fields = value.get("fields", [])
        if not isinstance(fields, list) or any(not isinstance(item, str) for item in fields):
            raise TypeError("output fields must be a string array")
        description = value.get("description", "")
        if not isinstance(description, str):
            raise TypeError("output description must be a string")
        return cls(
            path=_relative_path(value.get("path"), "output path"),
            format=value.get("format"),  # type: ignore[arg-type]
            fields=tuple(fields),
            required=value.get("required", True),  # type: ignore[arg-type]
            description=description,
        )


@dataclass(frozen=True)
class AlgorithmProblemContract:
    schema_version: str
    problem_id: str
    problem_type: str
    statement: str
    inputs: tuple[InputSpec, ...]
    decision_variables: tuple[str, ...]
    objective: ObjectiveSpec
    hard_constraints: tuple[ConstraintSpec, ...]
    soft_constraints: tuple[ConstraintSpec, ...]
    success_criteria: tuple[str, ...]
    deliverables: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    evolution: EvolutionSpec = field(default_factory=EvolutionSpec)
    outputs: tuple[OutputSpec, ...] = ()

    def __post_init__(self) -> None:
        _text(self.schema_version, "contract schema version", limit=64)
        _safe_segment(self.problem_id, "problem id")
        if self.problem_type not in SUPPORTED_PROBLEM_TYPES:
            raise ValueError("problem type is unsupported")
        _text(self.statement, "problem statement")
        if not self.inputs or len(self.inputs) > MAX_ITEMS:
            raise ValueError("contract inputs must be a bounded non-empty array")
        input_paths = [item.path for item in self.inputs]
        if len(input_paths) != len(set(input_paths)):
            raise ValueError("input paths must be unique")
        if not self.decision_variables or len(self.decision_variables) > MAX_ITEMS:
            raise ValueError("decision_variables must be a bounded non-empty array")
        _strings(list(self.decision_variables), "decision_variables")
        all_constraints = [*self.hard_constraints, *self.soft_constraints]
        if len(all_constraints) > MAX_ITEMS:
            raise ValueError("contract has too many constraints")
        ids = [item.id for item in all_constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint IDs must be unique")
        _strings(list(self.success_criteria), "success_criteria")
        _strings(list(self.deliverables), "deliverables")
        if not self.success_criteria or not self.deliverables:
            raise ValueError("success_criteria and deliverables must not be empty")
        _strings(list(self.assumptions), "assumptions")
        if len(self.outputs) > MAX_OUTPUTS or any(not isinstance(item, OutputSpec) for item in self.outputs):
            raise ValueError("outputs must be a bounded OutputSpec array")
        output_paths = [item.path for item in self.outputs]
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("output paths must be unique")
        _json_size(self.to_dict(), "algorithm problem contract")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "problem_type": self.problem_type,
            "statement": self.statement,
            "inputs": [item.to_dict() for item in self.inputs],
            "decision_variables": list(self.decision_variables),
            "objective": self.objective.to_dict(),
            "hard_constraints": [item.to_dict() for item in self.hard_constraints],
            "soft_constraints": [item.to_dict() for item in self.soft_constraints],
            "success_criteria": list(self.success_criteria),
            "deliverables": list(self.deliverables),
            "assumptions": list(self.assumptions),
            "evolution": self.evolution.to_dict(),
        }
        # Omit the optional field when empty so old contract digests remain stable.
        if self.outputs:
            payload["outputs"] = [item.to_dict() for item in self.outputs]
        return payload

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> AlgorithmProblemContract:
        if not isinstance(value, dict):
            raise TypeError("algorithm_problem must be an object")
        raw_inputs = value.get("inputs")
        if not isinstance(raw_inputs, list):
            raise TypeError("algorithm_problem inputs must be an array")
        raw_hard = value.get("hard_constraints", [])
        raw_soft = value.get("soft_constraints", [])
        raw_outputs = value.get("outputs", [])
        if not isinstance(raw_hard, list) or not isinstance(raw_soft, list):
            raise TypeError("constraints must be arrays")
        if not isinstance(raw_outputs, list):
            raise TypeError("outputs must be an array")
        return cls(
            schema_version=_text(value.get("schema_version", "1"), "contract schema version", limit=64),
            problem_id=_safe_segment(value.get("problem_id"), "problem id"),
            problem_type=_text(value.get("problem_type"), "problem type", limit=64),
            statement=_text(value.get("statement"), "problem statement"),
            inputs=tuple(InputSpec.from_dict(item) for item in raw_inputs),
            decision_variables=_strings(value.get("decision_variables"), "decision_variables"),
            objective=ObjectiveSpec.from_dict(value.get("objective")),
            hard_constraints=tuple(ConstraintSpec.from_dict(item) for item in raw_hard),
            soft_constraints=tuple(ConstraintSpec.from_dict(item) for item in raw_soft),
            success_criteria=_strings(value.get("success_criteria"), "success_criteria"),
            deliverables=_strings(value.get("deliverables"), "deliverables"),
            assumptions=_strings(value.get("assumptions"), "assumptions"),
            evolution=EvolutionSpec.from_dict(value.get("evolution")),
            outputs=tuple(OutputSpec.from_dict(item) for item in raw_outputs),
        )


@dataclass(frozen=True)
class EvaluationReport:
    schema_version: str
    evaluator_id: str
    validity: int
    combined_score: float
    detailed_scores: dict[str, dict[str, Any]]
    error_info: tuple[dict[str, str], ...]
    quality: float | None = None

    def __post_init__(self) -> None:
        _text(self.schema_version, "report schema version", limit=64)
        _safe_segment(self.evaluator_id, "evaluator id")
        if self.validity not in {0, 1} or isinstance(self.validity, bool):
            raise ValueError("validity must be 0 or 1")
        if isinstance(self.combined_score, bool) or not isinstance(self.combined_score, (int, float)) or not math.isfinite(float(self.combined_score)) or self.combined_score < 0:
            raise ValueError("combined_score must be a finite non-negative number")
        if self.validity == 0 and self.combined_score != 0:
            raise ValueError("combined_score must be zero when validity is zero")
        if self.quality is not None and (isinstance(self.quality, bool) or not isinstance(self.quality, (int, float)) or not math.isfinite(float(self.quality)) or self.quality < 0):
            raise ValueError("quality must be finite and non-negative")
        if not isinstance(self.detailed_scores, dict) or len(self.detailed_scores) > MAX_METRICS:
            raise ValueError("detailed_scores must be a bounded object")
        for name, detail in self.detailed_scores.items():
            _safe_segment(name, "detailed score name")
            if not isinstance(detail, dict) or set(detail) != {"value", "direction"}:
                raise ValueError("each detailed score must contain value and direction")
            value = detail["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError("detailed score value must be finite")
            if detail["direction"] not in {"maximize", "minimize"}:
                raise ValueError("detailed score direction must be maximize or minimize")
        if len(self.error_info) > MAX_ERROR_INFO:
            raise ValueError("error_info is too large")
        if self.validity == 0 and not self.error_info:
            raise ValueError("invalid report requires error_info")
        for item in self.error_info:
            if not isinstance(item, dict) or set(item) != {"code", "message"}:
                raise ValueError("each error_info entry must contain code and message")
            _safe_segment(item["code"], "error code")
            _text(item["message"], "error message", limit=512)
        _json_size(self.to_dict(), "evaluation report", limit=MAX_REPORT_BYTES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluator_id": self.evaluator_id,
            "validity": self.validity,
            "quality": self.quality,
            "combined_score": self.combined_score,
            "detailed_scores": self.detailed_scores,
            "error_info": list(self.error_info),
        }

    @classmethod
    def from_dict(cls, value: object) -> EvaluationReport:
        if not isinstance(value, dict):
            raise TypeError("evaluation report must be an object")
        raw_errors = value.get("error_info", [])
        if not isinstance(raw_errors, list):
            raise TypeError("error_info must be an array")
        return cls(
            schema_version=_text(value.get("schema_version", "1"), "report schema version", limit=64),
            evaluator_id=_safe_segment(value.get("evaluator_id"), "evaluator id"),
            validity=value.get("validity"),  # type: ignore[arg-type]
            quality=value.get("quality"),  # type: ignore[arg-type]
            combined_score=value.get("combined_score"),  # type: ignore[arg-type]
            detailed_scores=value.get("detailed_scores"),  # type: ignore[arg-type]
            error_info=tuple(raw_errors),  # type: ignore[arg-type]
        )


WORKSPACE_DIRECTORIES = {
    "raw_data": "data/raw",
    "processed_data": "data/processed",
    "solver": "solve",
    "evaluator": "evaluate",
    "output": "output",
    "evolution": "evolution",
}


def materialize_algorithm_workspace(
    root: str | Path, contract: AlgorithmProblemContract, plan_id: str, plan_version: int
) -> Path:
    """Create the fixed role directories and write a digest-bearing manifest."""
    raw_root = Path(root).expanduser()
    if raw_root.is_symlink():
        raise ValueError("algorithm workspace root must not be a symlink")
    root_path = raw_root.resolve()
    _safe_segment(plan_id, "plan id")
    if isinstance(plan_version, bool) or not isinstance(plan_version, int) or plan_version < 1:
        raise ValueError("plan version must be a positive integer")
    root_path.mkdir(parents=True, exist_ok=True)
    for relative in WORKSPACE_DIRECTORIES.values():
        directory = root_path / relative
        if directory.is_symlink():
            raise ValueError(f"algorithm workspace directory must not be a symlink: {relative}")
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.resolve().relative_to(root_path)
        except ValueError as exc:
            raise ValueError(f"algorithm workspace directory escapes root: {relative}") from exc
    payload = {
        "schema_version": "1",
        "problem_id": contract.problem_id,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "contract_sha256": contract.digest(),
        "evolution_strategy": contract.evolution.strategy,
        "directories": dict(WORKSPACE_DIRECTORIES),
    }
    manifest = root_path / "algorithm-workspace.json"
    temporary = root_path / ".algorithm-workspace.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest)
    return manifest
