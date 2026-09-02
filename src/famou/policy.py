"""Local Master policy and immutable plan contracts.

The policy is deliberately deterministic and runtime-neutral.  It provides the durable seam for a
model-backed planner later without importing Hermes, OpenCode, or any network service.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from .algorithm import AlgorithmProblemContract
from .budget import BudgetSpec
from .evaluator import validate_acceptance

Action = Literal["answer", "ask_user", "execute_plan", "patch_plan", "replan", "deliver"]
MAX_TEXT_BYTES = 8_000
MAX_ITEMS = 32
MAX_QUESTIONS = 4
SECRET_RE = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)")


def _text(value: object, field_name: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"{field_name} must be a string")
        return ""
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"{field_name} exceeds {MAX_TEXT_BYTES} bytes")
    if SECRET_RE.search(value):
        raise ValueError(f"{field_name} contains credential-like content")
    return value


def _strings(value: object, field_name: str, *, max_items: int = MAX_ITEMS) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"{field_name} must be a bounded string array")
    return tuple(_text(item, field_name, required=True) for item in value)


def validate_reason(value: object, field_name: str = "reason") -> str:
    """Validate a durable plan/revision reason without exposing the private helper."""
    return _text(value, field_name, required=True)


def validate_evidence(value: object, field_name: str = "evidence") -> tuple[str, ...]:
    """Validate bounded evidence attached to a plan revision or decision."""
    return _strings(value, field_name)


def _json_object(value: object, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > 20_000 or SECRET_RE.search(encoded):
        raise ValueError(f"{field_name} is too large or contains credential-like content")
    return value


@dataclass(frozen=True)
class PlanTask:
    id: str
    title: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    acceptance: str | dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.id or self.id in {".", ".."} or "/" in self.id or "\\" in self.id:
            raise ValueError(f"task id is not a safe path segment: {self.id!r}")
        _text(self.title, "task title", required=True)
        _text(self.prompt, "task prompt", required=True)
        if len(self.depends_on) > MAX_ITEMS or len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"dependencies for task {self.id} are invalid")
        for dependency in self.depends_on:
            if not isinstance(dependency, str) or not dependency.strip():
                raise ValueError(f"dependencies for task {self.id} must be non-empty IDs")
        if self.acceptance is not None:
            if not isinstance(self.acceptance, (str, dict)):
                raise ValueError(f"acceptance for task {self.id} must be a string or object")
            if isinstance(self.acceptance, str):
                _text(self.acceptance, "task acceptance")
            else:
                _json_object(self.acceptance, "task acceptance")
            validate_acceptance(self.acceptance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prompt": self.prompt,
            "depends_on": list(self.depends_on),
            "acceptance": self.acceptance,
        }

    @classmethod
    def from_dict(cls, payload: object) -> PlanTask:
        if not isinstance(payload, dict):
            raise TypeError("task must be an object")
        dependencies = payload.get("depends_on", payload.get("dependencies", []))
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            raise ValueError("task dependencies must be a string array")
        return cls(
            id=_text(payload.get("id"), "task id", required=True),
            title=_text(payload.get("title", payload.get("id")), "task title", required=True),
            prompt=_text(payload.get("prompt"), "task prompt", required=True),
            depends_on=tuple(dependencies),
            acceptance=payload.get("acceptance"),
        )


@dataclass(frozen=True)
class PlanDocument:
    goal: str
    tasks: tuple[PlanTask, ...]
    plan_id: str = field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:12]}")
    version: int = 1
    parent_version: int | None = None
    schema_version: str = "1"
    hard_constraints: tuple[str, ...] = ()
    soft_constraints: tuple[str, ...] = ()
    objective: str | dict[str, Any] = ""
    evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    acceptance: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    delivery: dict[str, Any] = field(default_factory=dict)
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    algorithm_problem: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _text(self.goal, "plan goal", required=True)
        _text(self.plan_id, "plan id", required=True)
        if self.plan_id in {".", ".."} or "/" in self.plan_id or "\\" in self.plan_id:
            raise ValueError(f"plan id is not a safe path segment: {self.plan_id!r}")
        if self.version < 1 or (self.parent_version is not None and self.parent_version >= self.version):
            raise ValueError("plan version must be positive and greater than its parent")
        if not self.tasks:
            raise ValueError("plan must contain at least one task")
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("plan contains duplicate task IDs")
        id_set = set(ids)
        graph = {task.id: task.depends_on for task in self.tasks}
        for task in self.tasks:
            unknown = set(task.depends_on) - id_set
            if unknown:
                raise ValueError(f"task {task.id} references unknown dependencies: {', '.join(sorted(unknown))}")
            if task.id in task.depends_on:
                raise ValueError(f"task {task.id} cannot depend on itself")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("plan dependencies contain a cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        _strings(list(self.hard_constraints), "hard constraints")
        _strings(list(self.soft_constraints), "soft constraints")
        _strings(list(self.evidence), "evidence")
        _strings(list(self.assumptions), "assumptions")
        if isinstance(self.objective, str):
            _text(self.objective, "objective")
        else:
            _json_object(self.objective, "objective")
        _json_object(self.acceptance, "acceptance")
        _json_object(self.verification, "verification")
        _json_object(self.delivery, "delivery")
        if not isinstance(self.budget, BudgetSpec):
            raise TypeError("plan budget must be a BudgetSpec")
        if self.algorithm_problem is not None:
            contract = AlgorithmProblemContract.from_dict(self.algorithm_problem)
            object.__setattr__(self, "algorithm_problem", contract.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "version": self.version,
            "parent_version": self.parent_version,
            "goal": self.goal,
            "hard_constraints": list(self.hard_constraints),
            "soft_constraints": list(self.soft_constraints),
            "objective": self.objective,
            "evidence": list(self.evidence),
            "assumptions": list(self.assumptions),
            "tasks": [task.to_dict() for task in self.tasks],
            "acceptance": self.acceptance,
            "verification": self.verification,
            "delivery": self.delivery,
            "budget": self.budget.to_dict(),
            **({"algorithm_problem": self.algorithm_problem} if self.algorithm_problem is not None else {}),
        }

    @classmethod
    def from_dict(cls, payload: object) -> PlanDocument:
        if not isinstance(payload, dict):
            raise TypeError("plan must be a JSON object")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list):
            raise TypeError("plan requires a tasks array")
        tasks = tuple(PlanTask.from_dict(item) for item in raw_tasks)
        return cls(
            goal=_text(payload.get("goal"), "plan goal", required=True),
            tasks=tasks,
            plan_id=_text(payload.get("plan_id", f"plan-{uuid.uuid4().hex[:12]}"), "plan id", required=True),
            version=int(payload.get("version", 1)),
            parent_version=int(payload["parent_version"]) if payload.get("parent_version") is not None else None,
            schema_version=str(payload.get("schema_version", "1")),
            hard_constraints=_strings(payload.get("hard_constraints"), "hard constraints"),
            soft_constraints=_strings(payload.get("soft_constraints"), "soft constraints"),
            objective=payload.get("objective", ""),
            evidence=_strings(payload.get("evidence"), "evidence"),
            assumptions=_strings(payload.get("assumptions"), "assumptions"),
            acceptance=_json_object(payload.get("acceptance"), "acceptance"),
            verification=_json_object(payload.get("verification"), "verification"),
            delivery=_json_object(payload.get("delivery"), "delivery"),
            budget=BudgetSpec.from_dict(payload.get("budget")),
            algorithm_problem=payload.get("algorithm_problem"),
        )


@dataclass(frozen=True)
class PlanPatch:
    plan_id: str
    base_version: int
    reason: str
    operations: tuple[dict[str, Any], ...]
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.plan_id, "plan id", required=True)
        _text(self.reason, "patch reason", required=True)
        if self.base_version < 1 or not self.operations or len(self.operations) > MAX_ITEMS:
            raise ValueError("patch requires a positive base version and bounded operations")
        _strings(list(self.evidence), "evidence")
        for operation in self.operations:
            if not isinstance(operation, dict) or not isinstance(operation.get("op"), str):
                raise TypeError("patch operation requires an op")
            if operation["op"] not in {"add_task", "remove_task", "update_task", "add_dependency", "remove_dependency", "update_acceptance", "update_constraints", "update_budget"}:
                raise ValueError(f"unsupported patch operation: {operation['op']}")
            _json_object(operation, "patch operation")

    @classmethod
    def from_dict(cls, payload: object) -> PlanPatch:
        if not isinstance(payload, dict):
            raise TypeError("patch must be a JSON object")
        operations = payload.get("operations")
        if not isinstance(operations, list):
            raise TypeError("patch requires an operations array")
        return cls(
            plan_id=_text(payload.get("plan_id"), "plan id", required=True),
            base_version=int(payload.get("base_version", 0)),
            reason=_text(payload.get("reason"), "patch reason", required=True),
            operations=tuple(operations),
            evidence=_strings(payload.get("evidence"), "evidence"),
        )


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    rationale: str
    confidence: float
    questions: tuple[str, ...] = ()
    plan_id: str | None = None
    plan_version: int | None = None
    evidence: tuple[str, ...] = ()
    plan: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.action not in {"answer", "ask_user", "execute_plan", "patch_plan", "replan", "deliver"}:
            raise ValueError(f"unsupported policy action: {self.action}")
        _text(self.rationale, "decision rationale", required=True)
        if not 0 <= self.confidence <= 1:
            raise ValueError("decision confidence must be between 0 and 1")
        if len(self.questions) > MAX_QUESTIONS:
            raise ValueError("a decision may contain at most four questions")
        for question in self.questions:
            _text(question, "question", required=True)
        _strings(list(self.evidence), "evidence")
        if self.plan_id is not None:
            _text(self.plan_id, "plan id", required=True)
        if self.plan_version is not None and self.plan_version < 1:
            raise ValueError("decision plan version must be positive")
        if self.plan is not None:
            plan = _json_object(self.plan, "decision plan")
            document = PlanDocument.from_dict(plan)
            if self.plan_id is not None and self.plan_id != document.plan_id:
                raise ValueError("decision plan id does not match its plan document")
            if self.plan_version is not None and self.plan_version != document.version:
                raise ValueError("decision plan version does not match its plan document")
        if self.action == "ask_user" and not self.questions:
            raise ValueError("ask_user decision requires questions")
        if self.action in {"patch_plan", "replan", "deliver"} and not self.plan_id:
            raise ValueError(f"{self.action} decision requires a plan reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "questions": list(self.questions),
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "evidence": list(self.evidence),
            **({"plan": self.plan} if self.plan is not None else {}),
        }


class MasterPolicy:
    """Small deterministic policy that can later be replaced/injected by a model planner."""

    def decide(self, goal: str) -> PolicyDecision:
        goal = _text(goal, "goal", required=True)
        lowered = goal.lower()
        missing_markers = (
            "need your choice",
            "which format",
            "please choose",
            "ask me",
            "missing information",
            "需要选择",
            "需要确认",
            "信息不足",
            "缺少信息",
            "请确认",
            "请指定",
        )
        if any(marker in lowered for marker in missing_markers):
            return PolicyDecision(
                "ask_user", "The goal is missing a material user decision", 0.9,
                questions=("Please provide the missing decision before I continue.",),
                evidence=("goal contains an explicit missing-information marker",),
            )
        complex_markers = (
            " and ",
            "then",
            "multiple",
            "steps",
            "files",
            "artifacts",
            "report",
            "verify",
            "tests",
            "plan",
            "并且",
            "然后",
            "多步骤",
            "多个",
            "文件",
            "报告",
            "验证",
            "测试",
            "计划",
        )
        work_markers = ("implement", "build", "deploy", "开发", "实现", "部署")
        if sum(marker in lowered for marker in complex_markers) >= 2 or any(
            marker in lowered for marker in work_markers
        ):
            plan = PlanDocument(
                goal=goal,
                tasks=(PlanTask("execute", "Execute goal", goal),),
                objective="complete the requested goal",
                verification={"required": True},
                delivery={"artifacts": True},
                evidence=("goal contains multiple observable work signals",),
            )
            return PolicyDecision(
                "execute_plan", "The goal has multiple observable work signals", 0.78,
                plan_id=plan.plan_id, plan_version=plan.version,
                evidence=plan.evidence, plan=plan.to_dict(),
            )
        return PolicyDecision("answer", "The goal appears self-contained and explainable", 0.82, evidence=("no multi-step work signal detected",))


def apply_patch(document: PlanDocument, patch: PlanPatch) -> PlanDocument:
    if patch.plan_id != document.plan_id or patch.base_version != document.version:
        raise ValueError("patch base plan/version does not match the current revision")
    tasks = list(document.tasks)
    by_id = {task.id: task for task in tasks}
    hard = list(document.hard_constraints)
    soft = list(document.soft_constraints)
    budget = document.budget
    for operation in patch.operations:
        op = operation["op"]
        task_id = str(operation.get("id", "")).strip()
        if op == "add_task":
            if not isinstance(operation.get("task"), dict):
                raise ValueError("add_task requires a task object")
            task = PlanTask.from_dict(operation["task"])
            if task.id in by_id:
                raise ValueError(f"task already exists: {task.id}")
            by_id[task.id] = task
            tasks.append(task)
        elif op == "remove_task":
            if task_id not in by_id:
                raise ValueError(f"unknown task: {task_id}")
            if any(task_id in task.depends_on for task in tasks):
                raise ValueError("cannot remove a task with dependents")
            tasks = [task for task in tasks if task.id != task_id]
            by_id.pop(task_id)
        elif op == "update_task":
            if task_id not in by_id:
                raise ValueError(f"unknown task: {task_id}")
            old = by_id[task_id]
            title = operation.get("title", old.title)
            prompt = operation.get("prompt", old.prompt)
            dependencies = operation.get("depends_on", old.depends_on)
            if not isinstance(dependencies, (list, tuple)):
                raise TypeError("update_task depends_on must be an array")
            updated = PlanTask(task_id, title, prompt, tuple(dependencies), operation.get("acceptance", old.acceptance))
            by_id[task_id] = updated
            tasks = [updated if task.id == task_id else task for task in tasks]
        elif op in {"add_dependency", "remove_dependency"}:
            dependency = str(operation.get("dependency", "")).strip()
            if task_id not in by_id or dependency not in by_id:
                raise ValueError("dependency operation references an unknown task")
            old = by_id[task_id]
            deps = list(old.depends_on)
            if op == "add_dependency" and dependency not in deps:
                deps.append(dependency)
            if op == "remove_dependency" and dependency in deps:
                deps.remove(dependency)
            updated = PlanTask(old.id, old.title, old.prompt, tuple(deps), old.acceptance)
            by_id[task_id] = updated
            tasks = [updated if task.id == task_id else task for task in tasks]
        elif op == "update_acceptance":
            if task_id not in by_id:
                raise ValueError(f"unknown task: {task_id}")
            old = by_id[task_id]
            updated = PlanTask(old.id, old.title, old.prompt, old.depends_on, operation.get("acceptance"))
            by_id[task_id] = updated
            tasks = [updated if task.id == task_id else task for task in tasks]
        elif op == "update_constraints":
            raw_hard = operation.get("hard_constraints", hard)
            raw_soft = operation.get("soft_constraints", soft)
            if not isinstance(raw_hard, (list, tuple)) or not isinstance(raw_soft, (list, tuple)):
                raise TypeError("update_constraints hard_constraints and soft_constraints must be arrays")
            hard = list(raw_hard)
            soft = list(raw_soft)
        elif op == "update_budget":
            budget = BudgetSpec.from_dict(operation.get("budget"))
    return PlanDocument(
        goal=document.goal, tasks=tuple(tasks), plan_id=document.plan_id, version=document.version + 1,
        parent_version=document.version, schema_version=document.schema_version,
        hard_constraints=tuple(hard), soft_constraints=tuple(soft), objective=document.objective,
        evidence=tuple(document.evidence) + patch.evidence, assumptions=document.assumptions,
        acceptance=document.acceptance, verification=document.verification, delivery=document.delivery,
        budget=budget, algorithm_problem=document.algorithm_problem,
    )
