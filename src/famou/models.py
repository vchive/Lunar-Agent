"""Small domain types shared by the controller and storage layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
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
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Run:
    id: str
    goal: str
    status: RunStatus
    workspace: Path
    created_at: str
    updated_at: str


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


@dataclass(frozen=True)
class Attempt:
    id: str
    task_id: str
    runtime: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
