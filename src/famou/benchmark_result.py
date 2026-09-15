"""Bounded, offline result receipts for a frozen benchmark comparison plan."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .benchmark_comparison import BenchmarkComparisonPlan

PROTOCOL = "lunar-benchmark-comparison-result-v1"
SCHEMA_VERSION = "1"
MAX_RESULT_BYTES = 128 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_STATUSES = {"completed", "stagnated", "failed", "cancelled"}


class BenchmarkResultError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise BenchmarkResultError(code)


def _strict(value: object, required: set[str], allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        _fail("benchmark_result_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("benchmark_result_invalid")
    if len(encoded) > MAX_RESULT_BYTES:
        _fail("benchmark_result_too_large")
    return encoded


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("benchmark_result_invalid")
    return value


def _evidence_path(value: object) -> str:
    """Normalize a descriptor path without allowing filesystem traversal."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _fail("benchmark_result_evidence_invalid")
    path = Path(value)
    if path.is_absolute() or value != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        _fail("benchmark_result_evidence_invalid")
    if len(value.encode("utf-8")) > 1024:
        _fail("benchmark_result_evidence_invalid")
    return path.as_posix()


def _result_id(comparison_id: str, arms: tuple[ComparisonArmResult, ...]) -> str:
    payload = {"protocol": PROTOCOL, "comparison_id": comparison_id, "arms": [a.to_dict() for a in sorted(arms, key=lambda a: a.arm_id)]}
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True)
class ComparisonArmResult:
    arm_id: str
    status: str
    elapsed_ms: int
    evaluated_candidates: int
    valid_candidates: int
    best_score: float | None
    evidence_sha256: str
    evidence_path: str | None = None
    evidence_size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.arm_id, str) or _SAFE_ID.fullmatch(self.arm_id) is None:
            _fail("benchmark_result_invalid")
        if self.status not in _STATUSES:
            _fail("benchmark_result_invalid")
        if isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, int) or not 0 <= self.elapsed_ms <= 86_400_000:
            _fail("benchmark_result_invalid")
        for value in (self.evaluated_candidates, self.valid_candidates):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000_000:
                _fail("benchmark_result_invalid")
        if self.valid_candidates > self.evaluated_candidates:
            _fail("benchmark_result_invalid")
        if self.best_score is not None and (isinstance(self.best_score, bool) or not isinstance(self.best_score, (int, float)) or not math.isfinite(float(self.best_score))):
            _fail("benchmark_result_invalid")
        _digest(self.evidence_sha256)
        if self.evidence_path is None:
            if self.evidence_size is not None:
                _fail("benchmark_result_evidence_invalid")
        else:
            normalized_path = _evidence_path(self.evidence_path)
            if isinstance(self.evidence_size, bool) or not isinstance(self.evidence_size, int) or not 0 <= self.evidence_size <= MAX_EVIDENCE_BYTES:
                _fail("benchmark_result_evidence_invalid")
            object.__setattr__(self, "evidence_path", normalized_path)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"arm_id": self.arm_id, "status": self.status, "elapsed_ms": self.elapsed_ms, "evaluated_candidates": self.evaluated_candidates, "valid_candidates": self.valid_candidates, "best_score": self.best_score, "evidence_sha256": self.evidence_sha256}
        if self.evidence_path is not None:
            result["evidence_path"] = self.evidence_path
            result["evidence_size"] = self.evidence_size
        return result

    @classmethod
    def from_dict(cls, value: object) -> ComparisonArmResult:
        fields = {"arm_id", "status", "elapsed_ms", "evaluated_candidates", "valid_candidates", "best_score", "evidence_sha256", "evidence_path", "evidence_size"}
        item = _strict(value, {"arm_id", "status", "elapsed_ms", "evaluated_candidates", "valid_candidates", "best_score", "evidence_sha256"}, fields)
        path = item.get("evidence_path")
        size = item.get("evidence_size")
        if (path is None) != (size is None):
            _fail("benchmark_result_evidence_invalid")
        return cls(item["arm_id"], item["status"], item["elapsed_ms"], item["evaluated_candidates"], item["valid_candidates"], item["best_score"], item["evidence_sha256"], path, size)  # type: ignore[arg-type]


@dataclass(frozen=True)
class BenchmarkComparisonResult:
    comparison_id: str
    result_id: str
    arms: tuple[ComparisonArmResult, ...]
    schema_version: str = SCHEMA_VERSION
    protocol: str = PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.protocol != PROTOCOL or not isinstance(self.comparison_id, str) or _SAFE_ID.fullmatch(self.comparison_id) is None or not isinstance(self.result_id, str) or _SHA256.fullmatch(self.result_id) is None:
            _fail("benchmark_result_invalid")
        if not 2 <= len(self.arms) <= 16 or any(not isinstance(a, ComparisonArmResult) for a in self.arms) or len({a.arm_id for a in self.arms}) != len(self.arms):
            _fail("benchmark_result_invalid")
        object.__setattr__(self, "arms", tuple(sorted(self.arms, key=lambda arm: arm.arm_id)))
        if self.result_id != _result_id(self.comparison_id, self.arms):
            _fail("benchmark_result_identity_mismatch")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "comparison_id": self.comparison_id, "result_id": self.result_id, "arms": [a.to_dict() for a in sorted(self.arms, key=lambda a: a.arm_id)]}

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> BenchmarkComparisonResult:
        item = _strict(value, {"schema_version", "protocol", "comparison_id", "result_id", "arms"}, {"schema_version", "protocol", "comparison_id", "result_id", "arms"})
        if not isinstance(item["arms"], list):
            _fail("benchmark_result_invalid")
        return cls(item["comparison_id"], item["result_id"], tuple(ComparisonArmResult.from_dict(a) for a in item["arms"]), item["schema_version"], item["protocol"])  # type: ignore[arg-type]


def parse_benchmark_comparison_result(source: str | os.PathLike[str] | Mapping[str, object]) -> BenchmarkComparisonResult:
    if isinstance(source, Mapping):
        result = BenchmarkComparisonResult.from_dict(dict(source))
        _canonical(result.to_dict())
        return result
    path = Path(source).expanduser()
    if path.is_symlink() or not path.is_file():
        _fail("benchmark_result_invalid")
    try:
        content = path.read_bytes()
    except OSError:
        _fail("benchmark_result_invalid")
    if not content or len(content) > MAX_RESULT_BYTES:
        _fail("benchmark_result_too_large")
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("benchmark_result_invalid")
            result[key] = value
        return result
    def constant(_value: str) -> object:
        _fail("benchmark_result_invalid")
    try:
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except BenchmarkResultError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _fail("benchmark_result_invalid")
    return BenchmarkComparisonResult.from_dict(payload)


def _verify_evidence(root: Path, arm: ComparisonArmResult) -> None:
    if arm.evidence_path is None or arm.evidence_size is None:
        _fail("benchmark_result_evidence_missing")
    raw = root / arm.evidence_path
    current = raw
    while current != root:
        if current.is_symlink():
            _fail("benchmark_result_evidence_unsafe")
        current = current.parent
    try:
        resolved = raw.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        _fail("benchmark_result_evidence_unsafe")
    if raw.is_symlink() or not resolved.is_file():
        _fail("benchmark_result_evidence_missing")
    try:
        descriptor = resolved.stat()
        if not stat.S_ISREG(descriptor.st_mode):
            _fail("benchmark_result_evidence_unsafe")
        if descriptor.st_size > MAX_EVIDENCE_BYTES:
            _fail("benchmark_result_evidence_changed")
        with resolved.open("rb") as stream:
            content = stream.read(arm.evidence_size + 1)
        after = resolved.stat()
    except OSError:
        _fail("benchmark_result_evidence_missing")
    if (
        descriptor.st_ino != after.st_ino
        or descriptor.st_dev != after.st_dev
        or descriptor.st_size != after.st_size
        or len(content) != arm.evidence_size
    ):
        _fail("benchmark_result_evidence_changed")
    if hashlib.sha256(content).hexdigest() != arm.evidence_sha256:
        _fail("benchmark_result_evidence_changed")


def admit_benchmark_comparison_result(
    result: BenchmarkComparisonResult | Mapping[str, object] | str | os.PathLike[str],
    plan: BenchmarkComparisonPlan,
    *,
    evidence_root: str | os.PathLike[str] | None = None,
) -> BenchmarkComparisonResult:
    if not isinstance(plan, BenchmarkComparisonPlan):
        _fail("benchmark_result_invalid")
    parsed = result if isinstance(result, BenchmarkComparisonResult) else parse_benchmark_comparison_result(result)
    # Reparse object instances so frozen-object mutation cannot bypass strict DTO checks.
    parsed = BenchmarkComparisonResult.from_dict(parsed.to_dict())
    if parsed.comparison_id != plan.comparison_id or {a.arm_id for a in parsed.arms} != {a.id for a in plan.arms}:
        _fail("benchmark_result_identity_mismatch")
    if evidence_root is not None:
        raw_root = Path(evidence_root).expanduser()
        absolute_root = raw_root.absolute()
        current_root = absolute_root
        while True:
            if current_root.is_symlink():
                _fail("benchmark_result_evidence_unsafe")
            if current_root == current_root.parent:
                break
            current_root = current_root.parent
        if raw_root.is_symlink() or not raw_root.is_dir():
            _fail("benchmark_result_evidence_unsafe")
        try:
            root = raw_root.resolve(strict=True)
        except OSError:
            _fail("benchmark_result_evidence_unsafe")
        for arm in parsed.arms:
            _verify_evidence(root, arm)
    return parsed


def bind_benchmark_comparison_result_evidence(
    result: BenchmarkComparisonResult | Mapping[str, object] | str | os.PathLike[str],
    plan: BenchmarkComparisonPlan,
    evidence_root: str | os.PathLike[str],
) -> BenchmarkComparisonResult:
    """Admit a result and require every arm's descriptor to match a local file."""
    return admit_benchmark_comparison_result(result, plan, evidence_root=evidence_root)


__all__ = [
    "BenchmarkComparisonResult", "BenchmarkResultError", "ComparisonArmResult",
    "admit_benchmark_comparison_result", "bind_benchmark_comparison_result_evidence",
    "parse_benchmark_comparison_result",
]
