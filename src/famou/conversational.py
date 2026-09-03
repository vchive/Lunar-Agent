"""Conversational intake for algorithm missions.

The compiler is deliberately a small, runtime-neutral boundary.  A model or local subprocess may
suggest a contract, but the existing ``AlgorithmProblemContract`` and ``PlanDocument`` validators
remain authoritative before any generated task is scheduled.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .algorithm import AlgorithmProblemContract
from .policy import PlanDocument, PlanTask
from .runtime import Runtime

MAX_GOAL_BYTES = 8_000
MAX_RESPONSE_BYTES = 64 * 1024
MAX_QUESTIONS = 4
MAX_OPTIONS = 10
MAX_QUESTION_BYTES = 2_000
MAX_OPTION_BYTES = 200
MAX_ANSWER_BYTES = 20_000
_SECRET_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)"
)

CompilationStatus = Literal["compiled", "needs_input"]


class ContractCompilationError(RuntimeError):
    """A compiler response could not be accepted as a safe algorithm contract."""


@dataclass(frozen=True, slots=True)
class CompilationQuestion:
    question: str
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be non-empty")
        question = self.question.strip()
        if len(question.encode("utf-8")) > MAX_QUESTION_BYTES or "\x00" in question:
            raise ValueError("question exceeds the bounded input limit")
        if _SECRET_RE.search(question):
            raise ValueError("question contains credential-like content")
        if len(self.options) > MAX_OPTIONS:
            raise ValueError("question has too many options")
        options: list[str] = []
        for option in self.options:
            if not isinstance(option, str) or not option.strip():
                raise ValueError("question options must be non-empty strings")
            normalized = option.strip()
            if len(normalized.encode("utf-8")) > MAX_OPTION_BYTES or "\x00" in normalized:
                raise ValueError("question option exceeds the bounded input limit")
            if _SECRET_RE.search(normalized):
                raise ValueError("question option contains credential-like content")
            options.append(normalized)
        if len(set(options)) != len(options):
            raise ValueError("question options must be unique")
        object.__setattr__(self, "question", question)
        object.__setattr__(self, "options", tuple(options))

    def to_dict(self) -> dict[str, object]:
        return {"question": self.question, "options": list(self.options)}


@dataclass(frozen=True, slots=True)
class CompilationResult:
    status: CompilationStatus
    contract: AlgorithmProblemContract | None = None
    questions: tuple[CompilationQuestion, ...] = ()
    plan: PlanDocument | None = None
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"compiled", "needs_input"}:
            raise ValueError("unsupported compilation status")
        if len(self.questions) > MAX_QUESTIONS:
            raise ValueError("a compilation result may contain at most four questions")
        if self.status == "compiled" and self.contract is None:
            raise ValueError("compiled result requires a contract")
        if self.status == "compiled" and self.questions:
            raise ValueError("compiled result must not contain questions")
        if self.status == "needs_input" and self.contract is not None:
            raise ValueError("needs_input result must not contain a contract")
        if self.status == "needs_input" and not self.questions:
            raise ValueError("needs_input result requires questions")
        if self.status == "needs_input" and self.plan is not None:
            raise ValueError("needs_input result must not contain a plan")
        for item in self.evidence:
            if not isinstance(item, str) or not item.strip() or len(item.encode("utf-8")) > 512:
                raise ValueError("compilation evidence is invalid")
            if _SECRET_RE.search(item):
                raise ValueError("compilation evidence contains credential-like content")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "questions": [item.to_dict() for item in self.questions],
            "evidence": list(self.evidence),
        }
        if self.contract is not None:
            payload["contract"] = self.contract.to_dict()
        if self.plan is not None:
            payload["plan"] = self.plan.to_dict()
        return payload


class ContractCompiler(Protocol):
    def compile(
        self,
        goal: str,
        workspace: Path,
        *,
        answer: str | None = None,
        timeout: float | None = None,
    ) -> CompilationResult:
        """Compile one bounded conversational turn into a contract or questions."""


def _bounded_goal(goal: str) -> str:
    if not isinstance(goal, str) or not goal.strip():
        raise ContractCompilationError("goal must be a non-empty string")
    goal = goal.strip()
    if "\x00" in goal or len(goal.encode("utf-8")) > MAX_GOAL_BYTES:
        raise ContractCompilationError("goal exceeds the bounded input limit")
    if _SECRET_RE.search(goal):
        raise ContractCompilationError("goal contains credential-like content")
    return goal


def _bounded_answer(answer: str | None) -> str | None:
    if answer is None:
        return None
    if not isinstance(answer, str) or not answer.strip():
        raise ContractCompilationError("answer must be a non-empty string")
    answer = answer.strip()
    if "\x00" in answer or len(answer.encode("utf-8")) > MAX_ANSWER_BYTES:
        raise ContractCompilationError("answer exceeds the bounded input limit")
    if _SECRET_RE.search(answer):
        raise ContractCompilationError("answer contains credential-like content")
    return answer


def _safe_error(error: Exception) -> str:
    """Keep compiler failures bounded and credential-safe before they reach the ledger."""
    message = _SECRET_RE.sub("[REDACTED]", str(error))
    return message[-2_000:] or type(error).__name__


def _questions(raw: object) -> tuple[CompilationQuestion, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_QUESTIONS:
        raise ContractCompilationError("needs_input requires one to four questions")
    result: list[CompilationQuestion] = []
    for item in raw:
        if isinstance(item, str):
            result.append(CompilationQuestion(item))
            continue
        if not isinstance(item, dict) or set(item) - {"question", "options"}:
            raise ContractCompilationError("question must contain only question and options")
        options = item.get("options", [])
        if not isinstance(options, list):
            raise ContractCompilationError("question options must be an array")
        try:
            result.append(CompilationQuestion(item.get("question"), tuple(options)))  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ContractCompilationError(str(exc)) from exc
    return tuple(result)


def _parse_response(raw: str) -> CompilationResult:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractCompilationError("compiler returned empty output")
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise ContractCompilationError("compiler response exceeds the bounded limit")
    if _SECRET_RE.search(raw):
        raise ContractCompilationError("compiler response contains credential-like content")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractCompilationError("compiler response must be one strict JSON object") from exc
    if not isinstance(payload, dict) or set(payload) - {"status", "contract", "questions", "evidence"}:
        raise ContractCompilationError("compiler response contains unknown fields")
    status = payload.get("status")
    if status == "needs_input":
        if "contract" in payload:
            raise ContractCompilationError("needs_input response must not include a contract")
        questions = _questions(payload.get("questions"))
        evidence = payload.get("evidence", [])
        if not isinstance(evidence, list):
            raise ContractCompilationError("compiler evidence must be an array")
        try:
            return CompilationResult("needs_input", questions=questions, evidence=tuple(evidence))
        except (TypeError, ValueError) as exc:
            raise ContractCompilationError(str(exc)) from exc
    if status != "compiled" or set(payload) - {"status", "contract", "evidence"} or "contract" not in payload:
        raise ContractCompilationError("compiler response must be status=compiled with contract")
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        raise ContractCompilationError("compiler evidence must be an array")
    try:
        _validate_contract_shape(payload["contract"])
        contract = AlgorithmProblemContract.from_dict(payload["contract"])
        return CompilationResult("compiled", contract=contract, evidence=tuple(evidence))
    except (TypeError, ValueError) as exc:
            raise ContractCompilationError(f"compiled contract is invalid: {exc}") from exc


def _validate_contract_shape(value: object) -> None:
    """Reject fields silently ignored by the legacy dataclass deserializers."""
    if not isinstance(value, dict):
        raise ContractCompilationError("contract must be a JSON object")
    allowed = {
        "schema_version",
        "problem_id",
        "problem_type",
        "statement",
        "inputs",
        "decision_variables",
        "objective",
        "hard_constraints",
        "soft_constraints",
        "success_criteria",
        "deliverables",
        "assumptions",
        "evolution",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ContractCompilationError(f"contract contains unknown fields: {', '.join(sorted(unknown))}")
    inputs = value.get("inputs")
    if isinstance(inputs, list):
        for item in inputs:
            if not isinstance(item, dict) or set(item) - {"path", "format", "fields", "key"}:
                raise ContractCompilationError("input contains unknown fields")
    objective = value.get("objective")
    if isinstance(objective, dict) and set(objective) - {"name", "direction", "metrics"}:
        raise ContractCompilationError("objective contains unknown fields")
    metrics = objective.get("metrics") if isinstance(objective, dict) else None
    if isinstance(metrics, list):
        for item in metrics:
            if not isinstance(item, dict) or set(item) - {"name", "direction", "weight"}:
                raise ContractCompilationError("objective metric contains unknown fields")
    for key in ("hard_constraints", "soft_constraints"):
        constraints = value.get(key)
        if isinstance(constraints, list):
            for item in constraints:
                if not isinstance(item, dict) or set(item) - {
                    "id",
                    "description",
                    "source",
                    "verification",
                    "result_fields",
                }:
                    raise ContractCompilationError("constraint contains unknown fields")
    evolution = value.get("evolution")
    if isinstance(evolution, dict) and set(evolution) - {"strategy", "max_rounds", "stagnation_rounds"}:
        raise ContractCompilationError("evolution contains unknown fields")


def build_algorithm_plan(goal: str, contract: AlgorithmProblemContract) -> PlanDocument:
    """Build the conservative baseline DAG used after intake succeeds."""
    problem_id = contract.problem_id
    plan_id = f"plan-{problem_id}-{contract.digest()[:8]}"
    tasks = (
        PlanTask(
            "data_discovery",
            "Discover and profile input data",
            "Inspect the declared input files under data/raw. Record observed schema, row counts, and data-quality issues in data/processed/data-profile.json. Do not invent missing fields or constraints.",
        ),
        PlanTask(
            "formulate",
            "Formulate the algorithm problem",
            "Using the validated contract and the verified data profile, restate decision variables, objective, provenance-backed constraints, and a measurable evaluation procedure. Write the formulation to solve/problem-formulation.md.",
            ("data_discovery",),
        ),
        PlanTask(
            "solve",
            "Implement a candidate algorithm",
            "Implement and test a candidate solution from the formulation. Keep source and reproducible run instructions under solve/ and write the requested deliverables under output/.",
            ("formulate",),
        ),
        PlanTask(
            "verify",
            "Independently verify the solution",
            "Review the candidate against every success criterion and hard constraint using observed data. Write a structured verification report under evaluate/ and identify any unresolved assumptions.",
            ("solve",),
        ),
    )
    return PlanDocument(
        goal=goal,
        plan_id=plan_id,
        tasks=tasks,
        objective=contract.objective.to_dict(),
        hard_constraints=tuple(item.description for item in contract.hard_constraints),
        soft_constraints=tuple(item.description for item in contract.soft_constraints),
        evidence=("contract compiled from an explicit conversational intake",),
        assumptions=contract.assumptions,
        acceptance={"required": True},
        verification={"required": True, "independent": True},
        delivery={"artifacts": list(contract.deliverables)},
        algorithm_problem=contract.to_dict(),
    )


def _default_contract(goal: str) -> AlgorithmProblemContract:
    """Repository-owned deterministic fallback for ``--runtime mock`` smoke tests."""
    lowered = goal.lower()
    if any(token in lowered for token in ("route", "配送", "路径")):
        problem_type = "routing"
        name = "routing objective"
    elif any(token in lowered for token in ("schedule", "排班", "调度")):
        problem_type = "scheduling"
        name = "scheduling objective"
    elif any(token in lowered for token in ("assign", "分配")):
        problem_type = "assignment"
        name = "assignment objective"
    elif any(token in lowered for token in ("pack", "装箱")):
        problem_type = "packing"
        name = "packing objective"
    else:
        problem_type = "continuous"
        name = "stated objective"
    digest = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:12]
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": f"mission-{digest}",
            "problem_type": problem_type,
            "statement": goal,
            "inputs": [
                {
                    "path": "input.json",
                    "format": "json",
                    "fields": {"records": "records supplied by the user"},
                }
            ],
            "decision_variables": ["algorithm solution"],
            "objective": {"name": name, "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Produce a reproducible solution and report its measured result."],
            "deliverables": ["algorithm source", "verification report"],
            "assumptions": ["Input schema, objective details, and hard constraints require user or data confirmation."],
            "evolution": {"strategy": "loop", "max_rounds": 3, "stagnation_rounds": 2},
        }
    )


class RuntimeContractCompiler:
    """Compile a strict JSON envelope using an explicit repository ``Runtime``."""

    def __init__(self, runtime: Runtime, *, mock_fallback: bool = True) -> None:
        self.runtime = runtime
        self.mock_fallback = mock_fallback

    def compile(
        self,
        goal: str,
        workspace: Path,
        *,
        answer: str | None = None,
        timeout: float | None = None,
    ) -> CompilationResult:
        goal = _bounded_goal(goal)
        answer = _bounded_answer(answer)
        if self.mock_fallback and getattr(self.runtime, "name", "") == "mock":
            contract = _default_contract(goal)
            return CompilationResult(
                "compiled",
                contract=contract,
                evidence=("repository mock compiler; no model response was used",),
            )
        prompt = self._prompt(goal, answer)
        try:
            result = self.runtime.run(prompt, workspace, timeout)
        except Exception as exc:
            raise ContractCompilationError(
                f"compiler runtime failed: {type(exc).__name__}: {_safe_error(exc)}"
            ) from exc
        try:
            return _parse_response(result.text)
        except ContractCompilationError:
            raise
        except Exception as exc:  # pragma: no cover - defensive normalization
            raise ContractCompilationError(f"compiler response could not be normalized: {exc}") from exc

    @staticmethod
    def _prompt(goal: str, answer: str | None) -> str:
        answer_section = (
            "\n\nA user answered the previous clarification question. Treat it as user-provided evidence; do not infer additional facts:\n"
            + answer
            if answer
            else ""
        )
        return (
            "You are Lunar-Agent's algorithm contract compiler. Return exactly one JSON object and no markdown. "
            "Use status=needs_input with one to four concise question objects when a material input, objective, "
            "hard constraint, or deliverable is unknown. Never invent user-confirmed constraints or data fields. "
            "Use status=compiled only when the nested contract is complete and conforms to this schema: "
            "schema_version, problem_id, problem_type (scheduling|routing|packing|assignment|forecasting|network_flow|continuous), "
            "statement, inputs (relative path, format, fields), decision_variables, objective (name,direction), "
            "hard_constraints and soft_constraints (id,description,source,verification,result_fields), "
            "success_criteria, deliverables, assumptions, and optional evolution. Constraint source must explicitly be "
            "user_confirmed, data_observed, or explicit_assumption. Questions have {question, options}. "
            "The top-level envelope is either {status,contract,evidence} or {status,questions,evidence}.\n\n"
            f"User goal:\n{goal}{answer_section}"
        )


@dataclass(frozen=True, slots=True)
class CallableContractCompiler:
    """Tiny test/integration seam for callers that already own a compiler function."""

    function: Callable[..., CompilationResult]
    name: str = "callable"

    def compile(
        self,
        goal: str,
        workspace: Path,
        *,
        answer: str | None = None,
        timeout: float | None = None,
    ) -> CompilationResult:
        result = self.function(goal, workspace, answer=answer, timeout=timeout)
        if not isinstance(result, CompilationResult):
            raise ContractCompilationError("compiler callable returned an invalid result")
        return result
