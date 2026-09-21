"""Offline frozen multi-arm comparison plans built from benchmark task envelopes."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import _benchmark_files as _files
from .benchmark_task import (
    BenchmarkTaskEnvelope,
    PhysicalAttemptBudget,
    admit_benchmark_task_envelope,
)

PROTOCOL = "lunar-benchmark-comparison-v1"
SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class BenchmarkComparisonError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise BenchmarkComparisonError(code)


def _strict(value: object, required: set[str], allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        _fail("benchmark_comparison_invalid")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("benchmark_comparison_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("benchmark_comparison_invalid")


def _derived_id(common: Mapping[str, object], protocol: str = PROTOCOL) -> str:
    return hashlib.sha256(_canonical({"protocol": protocol, **dict(common)})).hexdigest()


@dataclass(frozen=True)
class ComparisonArm:
    id: str
    envelope: BenchmarkTaskEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _SAFE_ID.fullmatch(self.id) is None:
            _fail("benchmark_comparison_invalid")
        if not isinstance(self.envelope, BenchmarkTaskEnvelope):
            _fail("benchmark_comparison_invalid")

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "envelope": self.envelope.to_dict()}


@dataclass(frozen=True)
class AdmittedComparisonArm:
    id: str
    envelope_sha256: str
    comparison_sha256: str


@dataclass(frozen=True)
class AdmittedBenchmarkComparison:
    comparison_id: str
    arms: tuple[AdmittedComparisonArm, ...]
    per_arm_attempts: int


@dataclass(frozen=True)
class BenchmarkComparisonPlan:
    comparison_id: str
    common: Mapping[str, object]
    arms: tuple[ComparisonArm, ...]
    schema_version: str = SCHEMA_VERSION
    protocol: str = PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.protocol != PROTOCOL:
            _fail("benchmark_comparison_invalid")
        if not isinstance(self.comparison_id, str) or _SAFE_ID.fullmatch(self.comparison_id) is None:
            _fail("benchmark_comparison_invalid")
        common = _strict(self.common, {"contract_sha256", "task_comparison_sha256", "model", "evaluator", "candidate", "budget"}, {"contract_sha256", "task_comparison_sha256", "model", "evaluator", "candidate", "budget"})
        _digest(common["contract_sha256"]); _digest(common["task_comparison_sha256"])
        if not isinstance(common["model"], dict) or not isinstance(common["evaluator"], dict) or not isinstance(common["candidate"], dict) or not isinstance(common["budget"], dict):
            _fail("benchmark_comparison_invalid")
        if not isinstance(self.arms, (tuple, list)) or len(self.arms) < 2 or len(self.arms) > 16 or any(not isinstance(a, ComparisonArm) for a in self.arms):
            _fail("benchmark_comparison_invalid")
        if len({a.id for a in self.arms}) != len(self.arms):
            _fail("benchmark_comparison_invalid")
        object.__setattr__(self, "common", dict(common))
        object.__setattr__(self, "arms", tuple(self.arms))
        if self.comparison_id != _derived_id(common, self.protocol):
            _fail("benchmark_comparison_identity_mismatch")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "comparison_id": self.comparison_id, "common": dict(self.common), "arms": [a.to_dict() for a in sorted(self.arms, key=lambda a: a.id)]}

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> BenchmarkComparisonPlan:
        item = _strict(value, {"schema_version", "protocol", "comparison_id", "common", "arms"}, {"schema_version", "protocol", "comparison_id", "common", "arms"})
        raw = item["arms"]
        if not isinstance(raw, list) or not 2 <= len(raw) <= 16:
            _fail("benchmark_comparison_invalid")
        arms: list[ComparisonArm] = []
        for entry in raw:
            part = _strict(entry, {"id", "envelope"}, {"id", "envelope"})
            arms.append(ComparisonArm(part["id"], BenchmarkTaskEnvelope.from_dict(part["envelope"])))  # type: ignore[arg-type]
        return cls(item["comparison_id"], item["common"], tuple(arms), item["schema_version"], item["protocol"])  # type: ignore[arg-type]

    @classmethod
    def from_envelopes(cls, envelopes: Mapping[str, BenchmarkTaskEnvelope]) -> BenchmarkComparisonPlan:
        if not isinstance(envelopes, Mapping) or not 2 <= len(envelopes) <= 16:
            _fail("benchmark_comparison_invalid")
        arms = tuple(ComparisonArm(key, value) for key, value in envelopes.items())
        first = arms[0].envelope
        common = {
            "contract_sha256": first.contract_sha256,
            "task_comparison_sha256": first.comparison_digest(),
            "model": first.model.to_dict(),
            "evaluator": first.evaluator.to_dict(),
            "candidate": dict(first.candidate),
            "budget": first.budget.to_dict(),
        }
        comparison_id = _derived_id(common)
        return cls(comparison_id, common, arms)


def parse_benchmark_comparison_plan(source: str | os.PathLike[str] | Mapping[str, object]) -> BenchmarkComparisonPlan:
    if isinstance(source, Mapping):
        return BenchmarkComparisonPlan.from_dict(dict(source))
    try:
        content = _files.read_regular_file(_files.absolute_path(source), 256 * 1024)
    except _files.BenchmarkFileError as exc:
        _fail("benchmark_comparison_too_large" if exc.reason == "too_large" else "benchmark_comparison_invalid")
    if not content or len(content) > 256 * 1024: _fail("benchmark_comparison_too_large")
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result: _fail("benchmark_comparison_invalid")
            result[key] = value
        return result
    def constant(_value: str) -> object: _fail("benchmark_comparison_invalid")
    try:
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except BenchmarkComparisonError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError): _fail("benchmark_comparison_invalid")
    return BenchmarkComparisonPlan.from_dict(payload)


def validate_benchmark_comparison_plan(plan: BenchmarkComparisonPlan) -> BenchmarkComparisonPlan:
    """Return an independent, strictly revalidated plan without reading any files.

    A frozen DTO can still contain mutable mappings or be modified through object-level
    operations. Rebuild its full JSON structure, then require every arm to match the frozen
    common task, model, evaluator, candidate and budget identities before it is admitted or
    used to bind a result. Construction alone keeps allowing plans to be drafted for validation.
    """
    if not isinstance(plan, BenchmarkComparisonPlan):
        _fail("benchmark_comparison_invalid")
    try:
        # The JSON round trip also detaches nested common mappings from the caller's object.
        parsed = BenchmarkComparisonPlan.from_dict(json.loads(_canonical(plan.to_dict())))
        for arm in parsed.arms:
            env = arm.envelope
            if (env.contract_sha256 != parsed.common["contract_sha256"]
                    or env.comparison_digest() != parsed.common["task_comparison_sha256"]
                    or env.model.to_dict() != parsed.common["model"]
                    or env.evaluator.to_dict() != parsed.common["evaluator"]
                    or dict(env.candidate) != parsed.common["candidate"]
                    or env.budget.to_dict() != parsed.common["budget"]):
                _fail("benchmark_comparison_identity_mismatch")
        return parsed
    except BenchmarkComparisonError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("benchmark_comparison_invalid")


def admit_benchmark_comparison_plan(
    plan: BenchmarkComparisonPlan | Mapping[str, object] | str | os.PathLike[str], *,
    contract_sha256: str, input_root: str | os.PathLike[str], model_profile_sha256: str,
    evaluator_fingerprint: str, budget: PhysicalAttemptBudget | Mapping[str, object] | None = None,
) -> AdmittedBenchmarkComparison:
    parsed = validate_benchmark_comparison_plan(
        plan if isinstance(plan, BenchmarkComparisonPlan) else parse_benchmark_comparison_plan(plan)
    )
    expected_budget = budget if isinstance(budget, PhysicalAttemptBudget) else (PhysicalAttemptBudget.from_dict(dict(budget)) if budget is not None else None)
    admitted: list[AdmittedComparisonArm] = []
    for arm in parsed.arms:
        env = arm.envelope
        result = admit_benchmark_task_envelope(env, contract_sha256=contract_sha256, input_root=input_root, model_profile_sha256=model_profile_sha256, evaluator_fingerprint=evaluator_fingerprint, budget=expected_budget)
        admitted.append(AdmittedComparisonArm(arm.id, result.envelope_sha256, result.comparison_sha256))
    return AdmittedBenchmarkComparison(parsed.comparison_id, tuple(admitted), parsed.arms[0].envelope.budget.attempts)


__all__ = ["AdmittedBenchmarkComparison", "BenchmarkComparisonError", "BenchmarkComparisonPlan", "ComparisonArm", "admit_benchmark_comparison_plan", "parse_benchmark_comparison_plan", "validate_benchmark_comparison_plan"]
