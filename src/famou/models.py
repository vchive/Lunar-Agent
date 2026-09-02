"""Small domain types shared by the controller and storage layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .budget import BudgetSpec


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Run:
    id: str
    goal: str
    status: RunStatus
    workspace: Path
    created_at: str
    updated_at: str
    runner_pid: int | None = None
    runner_pgid: int | None = None
    current_plan_id: str | None = None
    current_plan_version: int | None = None
    route_domain: str | None = None
    route_reason: str | None = None
    route_confidence: float | None = None
    solver_profile: str | None = None
    evaluator_profile: str | None = None
    route_required_capabilities: tuple[str, ...] = ()
    route_evidence: tuple[str, ...] = ()
    budget: BudgetSpec | None = None


@dataclass(frozen=True)
class Task:
    id: str
    run_id: str
    title: str
    prompt: str
    state: TaskStatus
    attempts: int
    result_path: Path | None
    last_error: str | None
    created_at: str
    updated_at: str
    dependencies: tuple[str, ...] = ()
    acceptance: str | None = None
    input_question: str | None = None
    input_options: tuple[str, ...] = ()
    input_answer_path: Path | None = None
    plan_task_id: str | None = None


@dataclass(frozen=True)
class Attempt:
    id: str
    task_id: str
    runtime: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    pid: int | None = None
    pgid: int | None = None
