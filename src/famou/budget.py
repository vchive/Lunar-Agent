"""Validated per-run execution budgets."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetSpec:
    max_tasks: int = 64
    max_attempts: int = 128
    max_tool_steps: int = 40
    max_runtime_seconds: float = 900.0
    max_artifact_bytes: int = 10 * 1024 * 1024

    def __post_init__(self) -> None:
        for name in ("max_tasks", "max_attempts", "max_tool_steps", "max_artifact_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.max_runtime_seconds, (int, float)) or isinstance(self.max_runtime_seconds, bool):
            raise TypeError("max_runtime_seconds must be finite and positive")
        if not math.isfinite(float(self.max_runtime_seconds)) or self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be finite and positive")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_tasks": self.max_tasks,
            "max_attempts": self.max_attempts,
            "max_tool_steps": self.max_tool_steps,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_artifact_bytes": self.max_artifact_bytes,
        }

    @classmethod
    def from_dict(cls, value: object | None) -> BudgetSpec:
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise TypeError("budget must be an object")
        allowed = {"max_tasks", "max_attempts", "max_tool_steps", "max_runtime_seconds", "max_artifact_bytes"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown budget fields: {', '.join(sorted(unknown))}")
        defaults = cls().to_dict()
        defaults.update(value)
        return cls(**defaults)


class BudgetExceeded(RuntimeError):
    """A run crossed one of its explicit limits."""

    def __init__(self, limit: str, actual: float, maximum: float) -> None:
        self.limit, self.actual, self.maximum = limit, actual, maximum
        super().__init__(f"budget limit {limit} exceeded ({actual} > {maximum})")
