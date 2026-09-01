"""Structured, local evaluation boundary."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Evaluation:
    passed: bool
    evidence: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "evidence": list(self.evidence), "reason": self.reason}


class Evaluator(Protocol):
    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        """Return an evidence-backed decision for one candidate result."""


class NonEmptyEvaluator:
    """Minimal P1 evaluator; P2 will add task-specific structured checks."""

    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        del workspace
        passed = bool(result.strip())
        return Evaluation(
            passed=passed,
            evidence=("result.txt contains non-empty output",) if passed else (),
            reason="result is non-empty" if passed else "result is empty",
        )


class ContainsEvaluator:
    """Accept a result only when it contains a required text fragment."""

    def __init__(self, expected: str) -> None:
        self.expected = expected

    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        del workspace
        passed = self.expected in result
        return Evaluation(
            passed=passed,
            evidence=(f"result contains {self.expected!r}",) if passed else (),
            reason=(
                f"result contains required text {self.expected!r}"
                if passed
                else f"result does not contain required text {self.expected!r}"
            ),
        )


def acceptance_evaluator(value: str | None) -> ContainsEvaluator | None:
    """Build the small built-in acceptance policy used by JSON plans.

    A string means ``contains``. An object is stored as JSON and currently supports
    ``{"contains": "..."}``, leaving room for future local policies without changing the schema.
    """
    if value is None:
        return None
    criterion: object = value
    try:
        criterion = json.loads(value)
    except json.JSONDecodeError:
        pass
    if isinstance(criterion, str) and criterion:
        return ContainsEvaluator(criterion)
    if isinstance(criterion, dict) and isinstance(criterion.get("contains"), str):
        return ContainsEvaluator(criterion["contains"])
    raise ValueError("acceptance must be a non-empty string or an object with a string 'contains'")
