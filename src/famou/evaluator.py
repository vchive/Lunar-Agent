"""Structured, local evaluation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Evaluation:
    passed: bool
    evidence: tuple[str, ...]
    reason: str


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
