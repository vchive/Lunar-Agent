"""Deterministic, advisory recovery decisions over durable local evidence.

Recovery deliberately has no Runtime Adapter dependency.  It identifies the next control-plane
boundary for a parent Agent without resuming work, revising a plan, or interpreting raw artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .models import Run, RunStatus, Task, TaskStatus

RecoveryAction = Literal[
    "none", "retry", "ask_user", "propose_patch", "propose_replan", "stop"
]

_ACTIONS: frozenset[str] = frozenset(
    {"none", "retry", "ask_user", "propose_patch", "propose_replan", "stop"}
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_RUNTIME_CONFIGURATION_MARKERS = (
    "permission",
    "authoriz",
    "credential",
    "api key",
    "command not found",
    "no such file",
    "configuration",
    "configur",
)
_RULE_NAMES = frozenset(
    {
        "result_contains",
        "artifact_exists",
        "artifact_text_contains",
        "json_parse",
        "json_has_keys",
        "all",
        "any",
    }
)
_MAX_EVIDENCE = 16
_MAX_QUESTIONS = 4


def _safe_identifier(value: str | None) -> str | None:
    """Return a controlled identifier, refusing values that could amplify sensitive text."""
    if value is None or not _SAFE_IDENTIFIER.fullmatch(value):
        return None
    lowered = value.lower()
    if "api_key" in lowered or "api-key" in lowered or lowered.startswith("sk-"):
        return None
    return value


def _bounded_evidence(values: list[str]) -> tuple[str, ...]:
    evidence: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
            continue
        if value not in evidence:
            evidence.append(value)
        if len(evidence) == _MAX_EVIDENCE:
            break
    return tuple(evidence)


@dataclass(frozen=True)
class RecoveryProposal:
    """A bounded, non-executable recommendation for the next owner action."""

    action: RecoveryAction
    run_id: str
    run_status: str
    rationale: str
    evidence: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    guidance: dict[str, object] = field(default_factory=dict)
    plan_id: str | None = None
    plan_version: int | None = None
    task_id: str | None = None
    plan_task_id: str | None = None
    artifact_path: str | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS:
            raise ValueError(f"unsupported recovery action: {self.action}")
        if not _safe_identifier(self.run_id):
            raise ValueError("recovery run_id must be a safe identifier")
        if self.run_status not in {status.value for status in RunStatus}:
            raise ValueError("recovery run_status is invalid")
        if not self.rationale or len(self.rationale.encode("utf-8")) > 1_000:
            raise ValueError("recovery rationale must be bounded non-empty text")
        if len(self.evidence) > _MAX_EVIDENCE or any(
            not isinstance(item, str) or not item or len(item.encode("utf-8")) > 256
            for item in self.evidence
        ):
            raise ValueError("recovery evidence is invalid")
        if len(self.questions) > _MAX_QUESTIONS or any(
            not isinstance(item, str) or not item or len(item.encode("utf-8")) > 1_000
            for item in self.questions
        ):
            raise ValueError("recovery questions are invalid")
        if not isinstance(self.guidance, dict):
            raise TypeError("recovery guidance must be an object")
        encoded = json.dumps(self.guidance, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 4_000:
            raise ValueError("recovery guidance exceeds 4 KiB")
        for value, field_name in (
            (self.plan_id, "plan_id"),
            (self.task_id, "task_id"),
            (self.plan_task_id, "plan_task_id"),
        ):
            if value is not None and not _safe_identifier(value):
                raise ValueError(f"recovery {field_name} must be a safe identifier")
        if self.plan_version is not None and self.plan_version < 1:
            raise ValueError("recovery plan_version must be positive")
        if self.artifact_path is not None and (
            not self.artifact_path.startswith("recovery/proposals/")
            or not self.artifact_path.endswith(".json")
        ):
            raise ValueError("recovery artifact_path must be a proposal path")

    def _payload_without_fingerprint(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "action": self.action,
            "run_id": self.run_id,
            "run_status": self.run_status,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "task_id": self.task_id,
            "plan_task_id": self.plan_task_id,
            "rationale": self.rationale,
            "evidence": list(self.evidence),
            "questions": list(self.questions),
            "guidance": self.guidance,
        }

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self._payload_without_fingerprint(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def event_id(self) -> str:
        return f"event-recovery-{self.run_id}-{self.fingerprint[:24]}"

    def with_artifact_path(self, path: str) -> RecoveryProposal:
        return replace(self, artifact_path=path)

    def to_dict(self) -> dict[str, object]:
        return {
            **self._payload_without_fingerprint(),
            "fingerprint": self.fingerprint,
            **({"artifact_path": self.artifact_path} if self.artifact_path is not None else {}),
        }


class RecoveryPolicy:
    """Pure deterministic recovery policy over run/task/event snapshots."""

    def propose(
        self,
        run: Run,
        tasks: list[Task],
        events: list[dict[str, Any]],
        pending_input: dict[str, Any] | None = None,
    ) -> RecoveryProposal:
        plan_id = _safe_identifier(run.current_plan_id)
        plan_version = run.current_plan_version if plan_id is not None else None
        base_evidence = [f"run_status:{run.status.value}"]

        if run.status == RunStatus.SUCCEEDED:
            return self._proposal(
                "none", run, "The run already has verified successful output.", base_evidence,
                plan_id=plan_id, plan_version=plan_version,
            )
        if run.status == RunStatus.CANCELLED:
            return self._proposal(
                "stop", run, "The run was cancelled and requires a new explicit start to continue.",
                base_evidence, {"terminal": True}, plan_id, plan_version,
            )
        if pending_input is not None or any(task.state == TaskStatus.WAITING and task.input_question for task in tasks):
            task = self._pending_input_task(tasks, pending_input)
            return self._proposal(
                "ask_user", run, "The run is waiting for an explicit user or parent-Agent answer.",
                base_evidence + ["input:pending"], {"input_request": True}, plan_id, plan_version,
                task, questions=("Answer the pending input request before resuming this run.",),
            )

        if run.status in {RunStatus.PENDING, RunStatus.RUNNING}:
            retryable = next((task for task in tasks if task.state in {TaskStatus.READY, TaskStatus.UNCERTAIN}), None)
            if retryable is not None:
                return self._proposal(
                    "retry", run, "Ready or recovered work can be resumed through the existing controller.",
                    base_evidence + [f"task_state:{retryable.state.value}"], {"command": "resume"},
                    plan_id, plan_version, retryable,
                )

        current_events = self._events_after_latest_plan_revision(events)
        budget = self._latest_event(current_events, "budget_exceeded")
        if budget is not None:
            limit = budget.get("payload", {}).get("limit")
            limit_code = limit if isinstance(limit, str) and limit in {
                "max_tasks", "max_attempts", "max_tool_steps", "max_runtime_seconds", "max_artifact_bytes"
            } else "unknown"
            return self._proposal(
                "propose_replan", run,
                "A configured execution budget was reached and must be reconsidered explicitly.",
                base_evidence + ["budget_exceeded", f"budget:{limit_code}"],
                {"preserve_verified_artifacts": True, "inspect": ["budget"]}, plan_id, plan_version,
                self._first_nonterminal_task(tasks),
            )

        failed_task = next((task for task in tasks if task.state == TaskStatus.FAILED), None)
        evaluation = self._latest_failed_evaluation(current_events, failed_task.id if failed_task else None)
        if failed_task is not None and evaluation is not None:
            rule = self._acceptance_rule(evaluation)
            evidence = base_evidence + ["task_state:failed", "evaluation:failed"]
            if rule is not None:
                evidence.append(f"acceptance:{rule}")
            if plan_id is not None and plan_version is not None and _safe_identifier(failed_task.plan_task_id):
                logical_id = failed_task.plan_task_id
                assert logical_id is not None
                return self._proposal(
                    "propose_patch", run,
                    "Independent acceptance verification failed for a planned task.", evidence,
                    {"required_operation": "update_task", "target": logical_id, "inspect": ["evaluation"]},
                    plan_id, plan_version, failed_task,
                )
            return self._proposal(
                "ask_user", run,
                "Independent verification failed, but this run has no versioned plan to revise.", evidence,
                {"versioned_plan_required": True, "inspect": ["evaluation"]}, plan_id, plan_version,
                failed_task,
                questions=("Provide a versioned replacement plan before retrying the failed task.",),
            )

        if failed_task is not None and self._needs_runtime_configuration(failed_task.last_error):
            return self._proposal(
                "ask_user", run,
                "The runtime needs explicit configuration or authority before it can continue.",
                base_evidence + ["task_state:failed", "runtime_failure:requires_configuration"],
                {"runtime_configuration": True}, plan_id, plan_version, failed_task,
                questions=("Provide or confirm the runtime configuration and authority required to continue.",),
            )

        if failed_task is not None and plan_id is not None:
            return self._proposal(
                "propose_replan", run,
                "A planned task exhausted its current recovery path without verified output.",
                base_evidence + ["task_state:failed", "runtime_failure:unclassified"],
                {"preserve_verified_artifacts": True, "inspect": ["failed_tasks"]},
                plan_id, plan_version, failed_task,
            )

        if failed_task is not None:
            return self._proposal(
                "ask_user", run,
                "The unplanned task failed and needs explicit next-step instructions.",
                base_evidence + ["task_state:failed", "runtime_failure:unclassified"],
                {"versioned_plan_required": True, "inspect": ["failed_tasks"]},
                plan_id, plan_version, failed_task,
                questions=("Provide a versioned plan or runtime instructions before retrying.",),
            )

        blocked = next((task for task in tasks if task.state == TaskStatus.BLOCKED), None)
        if blocked is not None:
            return self._proposal(
                "propose_replan", run,
                "A task is blocked by a prerequisite that did not produce verified output.",
                base_evidence + ["task_state:blocked"],
                {"preserve_verified_artifacts": True, "inspect": ["failed_tasks"]},
                plan_id, plan_version, blocked,
            )

        return self._proposal(
            "none", run, "No actionable recovery evidence is currently available.", base_evidence,
            plan_id=plan_id, plan_version=plan_version,
        )

    @staticmethod
    def _events_after_latest_plan_revision(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_revision = max(
            (index for index, event in enumerate(events) if event.get("type") == "plan_revision_created"),
            default=-1,
        )
        return events[latest_revision + 1 :]

    @staticmethod
    def _latest_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
        return next((event for event in reversed(events) if event.get("type") == event_type), None)

    @staticmethod
    def _latest_failed_evaluation(
        events: list[dict[str, Any]], task_id: str | None
    ) -> dict[str, Any] | None:
        if task_id is None:
            return None
        return next(
            (
                event
                for event in reversed(events)
                if event.get("type") == "task_evaluated"
                and event.get("task_id") == task_id
                and event.get("payload", {}).get("passed") is False
            ),
            None,
        )

    @staticmethod
    def _acceptance_rule(event: dict[str, Any]) -> str | None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None
        details = payload.get("details")
        if not isinstance(details, dict):
            return None
        acceptance = details.get("acceptance")
        if not isinstance(acceptance, dict):
            return None
        check = acceptance.get("check")
        if not isinstance(check, dict):
            return None
        rule = check.get("rule")
        return rule if isinstance(rule, str) and rule in _RULE_NAMES else None

    @staticmethod
    def _needs_runtime_configuration(error: str | None) -> bool:
        if not isinstance(error, str):
            return False
        lowered = error.lower()
        return any(marker in lowered for marker in _RUNTIME_CONFIGURATION_MARKERS)

    @staticmethod
    def _pending_input_task(tasks: list[Task], pending_input: dict[str, Any] | None) -> Task | None:
        pending_id = pending_input.get("task_id") if isinstance(pending_input, dict) else None
        return next(
            (task for task in tasks if task.id == pending_id),
            next((task for task in tasks if task.state == TaskStatus.WAITING and task.input_question), None),
        )

    @staticmethod
    def _first_nonterminal_task(tasks: list[Task]) -> Task | None:
        return next(
            (
                task
                for task in tasks
                if task.state not in {TaskStatus.SUCCEEDED, TaskStatus.SUPERSEDED, TaskStatus.CANCELLED}
            ),
            tasks[0] if tasks else None,
        )

    @staticmethod
    def _proposal(
        action: RecoveryAction,
        run: Run,
        rationale: str,
        evidence: list[str],
        guidance: dict[str, object] | None = None,
        plan_id: str | None = None,
        plan_version: int | None = None,
        task: Task | None = None,
        *,
        questions: tuple[str, ...] = (),
    ) -> RecoveryProposal:
        return RecoveryProposal(
            action=action,
            run_id=run.id,
            run_status=run.status.value,
            rationale=rationale,
            evidence=_bounded_evidence(evidence),
            questions=questions,
            guidance=guidance or {},
            plan_id=plan_id,
            plan_version=plan_version,
            task_id=_safe_identifier(task.id) if task else None,
            plan_task_id=_safe_identifier(task.plan_task_id) if task else None,
        )
