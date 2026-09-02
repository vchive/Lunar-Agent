"""Named solver and evaluator profiles, independent from Runtime adapters."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .budget import BudgetSpec
from .evaluator import Evaluator, NonEmptyEvaluator

_SECRET_RE = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)")


def _profile_text(value: str, name: str) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not value or len(value.encode("utf-8")) > 8_000 or _SECRET_RE.search(value):
        raise ValueError(f"{name} must be bounded and contain no credential-like content")
    return value


@dataclass(frozen=True)
class SolverProfile:
    name: str
    description: str
    required_capabilities: tuple[str, ...]
    budget: BudgetSpec = field(default_factory=BudgetSpec)

    def __post_init__(self) -> None:
        _profile_text(self.name, "solver profile name")
        _profile_text(self.description, "solver profile description")
        if len(self.required_capabilities) > 16:
            raise ValueError("solver profile has too many capabilities")
        for capability in self.required_capabilities:
            _profile_text(capability, "solver capability")


@dataclass(frozen=True)
class EvaluatorProfile:
    name: str
    description: str
    factory: Callable[[], Evaluator]

    def __post_init__(self) -> None:
        _profile_text(self.name, "evaluator profile name")
        _profile_text(self.description, "evaluator profile description")
        if not callable(self.factory):
            raise TypeError("evaluator profile factory must be callable")

    def create(self) -> Evaluator:
        return self.factory()


class ProfileRegistry:
    def __init__(self, solvers: tuple[SolverProfile, ...] | None = None, evaluators: tuple[EvaluatorProfile, ...] | None = None) -> None:
        solver_items = solvers or self._default_solvers()
        evaluator_items = evaluators or self._default_evaluators()
        if len({item.name for item in solver_items}) != len(solver_items):
            raise ValueError("solver profile names must be unique")
        if len({item.name for item in evaluator_items}) != len(evaluator_items):
            raise ValueError("evaluator profile names must be unique")
        self.solvers = {item.name: item for item in solver_items}
        self.evaluators = {item.name: item for item in evaluator_items}

    @staticmethod
    def _default_solvers() -> tuple[SolverProfile, ...]:
        return tuple(
            SolverProfile(name, f"{name} local solver", capabilities)
            for name, capabilities in {
                "general": ("read_files", "write_artifacts"),
                "data": ("read_files", "write_files", "analyze_data", "write_artifacts"),
                "research": ("read_files", "gather_sources", "write_artifacts"),
                "coding": ("read_files", "write_files", "run_tests", "write_artifacts"),
            }.items()
        )

    @staticmethod
    def _default_evaluators() -> tuple[EvaluatorProfile, ...]:
        return tuple(EvaluatorProfile(name, f"{name} structured evaluator", NonEmptyEvaluator) for name in ("general", "data", "research", "coding"))

    def solver(self, name: str) -> SolverProfile:
        try:
            return self.solvers[name]
        except KeyError as exc:
            raise ValueError(f"unknown solver profile: {name}") from exc

    def evaluator(self, name: str) -> Evaluator:
        try:
            return self.evaluators[name].create()
        except KeyError as exc:
            raise ValueError(f"unknown evaluator profile: {name}") from exc
