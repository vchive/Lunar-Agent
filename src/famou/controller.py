"""Durable orchestration loop for the standalone local agent."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from typing import Any

from .artifacts import ArtifactError, ArtifactStore
from .config import Config
from .evaluator import Evaluation, Evaluator, NonEmptyEvaluator, acceptance_evaluator
from .models import Run, RunStatus
from .runtime import Runtime, RuntimeExecutionError
from .store import Store


class LocalController:
    def __init__(
        self,
        config: Config,
        runtime: Runtime,
        evaluator: Evaluator | None = None,
        store: Store | None = None,
    ) -> None:
        self.config = config
        self.config.ensure()
        self.store = store or Store(config.database)
        self.store.initialize()
        self.runtime = runtime
        self.evaluator = evaluator or NonEmptyEvaluator()

    def start(self, goal: str, plan_tasks: list[dict[str, Any]] | None = None) -> Run:
        run = self.create(goal, plan_tasks)
        return self.resume(run.id)

    def create(self, goal: str, plan_tasks: list[dict[str, Any]] | None = None) -> Run:
        """Persist a run and its initial task without executing it."""
        run = self.store.create_run(goal, tasks=plan_tasks)
        Path(run.workspace).mkdir(parents=True, exist_ok=True)
        return run

    def resume(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run

        self.store.recover_running(run_id)
        run = self.store.get_run(run_id)
        assert run is not None
        try:
            while True:
                task = self.store.next_task(run_id)
                if task is None:
                    break
                attempt = self.store.claim_task(task.id, self.runtime.name)
                if attempt is None:
                    continue
                task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
                artifacts = ArtifactStore(run.workspace, self.store, run_id)
                prompt = self._build_task_prompt(run, task)
                artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/prompt.md",
                    prompt,
                    task.id,
                    kind="prompt",
                )
                try:
                    set_observer = getattr(self.runtime, "set_process_observer", None)
                    if callable(set_observer):
                        set_observer(
                            lambda pid, pgid: self.store.set_attempt_process(attempt.id, pid, pgid)
                        )
                    result = self.runtime.run(prompt, task_root, self.config.runtime_timeout)
                    if not self._task_is_running(task.id):
                        self._discard_late_result(run_id, task.id, attempt.id)
                        continue
                    result_path = artifacts.write_text(
                        f"tasks/{task.id}/{attempt.id}/result.txt",
                        result.text,
                        task.id,
                    )
                    for relative_path in result.artifacts:
                        runtime_path = self._runtime_artifact_path(task_root, relative_path)
                        artifacts.record(runtime_path, task.id, kind="runtime")
                    evaluation = self._evaluate(task, result.text, task_root)
                    evaluation_payload = {
                        "attempt_id": attempt.id,
                        "passed": evaluation.passed,
                        "reason": evaluation.reason,
                        "evidence": list(evaluation.evidence),
                    }
                    self.store.append_event(
                        run_id,
                        "task_evaluated",
                        evaluation_payload,
                        task_id=task.id,
                    )
                    # Keep the decision as a run-scoped file for auditability. Evaluation files are
                    # intentionally not counted as user output artifacts so the stable P1 artifact
                    # contract remains prompt + result (runtime-produced files are still indexed).
                    evaluation_path = artifacts.safe_path(
                        f"tasks/{task.id}/{attempt.id}/evaluation.json"
                    )
                    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
                    evaluation_path.write_text(
                        json.dumps(evaluation_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    if not self._task_is_running(task.id):
                        self._discard_late_result(run_id, task.id, attempt.id)
                        continue
                    relative_result = str(result_path.relative_to(Path(run.workspace)))
                    if evaluation.passed:
                        self.store.finish_task(task.id, attempt.id, True, relative_result)
                    elif self._can_retry(task.attempts + 1):
                        self.store.retry_task(task.id, attempt.id, evaluation.reason)
                    else:
                        self.store.finish_task(task.id, attempt.id, False, relative_result, evaluation.reason)
                except Exception as exc:  # noqa: BLE001 - runtime boundary must persist all failures
                    error = self._sanitize_error(exc)
                    if not self._task_is_running(task.id):
                        self._discard_late_result(run_id, task.id, attempt.id, error)
                    elif self._can_retry(task.attempts + 1):
                        self.store.retry_task(task.id, attempt.id, error)
                    else:
                        self.store.finish_task(task.id, attempt.id, False, error=error)
                finally:
                    if callable(getattr(self.runtime, "set_process_observer", None)):
                        self.runtime.set_process_observer(None)
        finally:
            # A synchronous controller has no runner identity; a detached child clears only its
            # own PID so a newer runner cannot be accidentally cleared.
            self.store.clear_runner_process(run_id, os.getpid())
        settled = self.store.settle_run(run_id)
        assert settled is not None
        return settled

    def cancel(self, run_id: str) -> bool:
        cancelled = self.store.cancel_run(run_id)
        if cancelled:
            self.runtime.cancel()
            run = self.store.get_run(run_id)
            if run is not None:
                self._terminate_process_group(run.runner_pid, run.runner_pgid)
                self.store.clear_runner_process(run_id)
        return cancelled

    def _task_is_running(self, task_id: str) -> bool:
        task = self.store.get_task(task_id)
        return task is not None and task.state.value == "running"

    def _evaluate(self, task: Any, result: str, workspace: Path) -> Evaluation:
        base = self.evaluator.evaluate(result, workspace)
        criterion = acceptance_evaluator(task.acceptance)
        if criterion is None:
            return base
        acceptance = criterion.evaluate(result, workspace)
        evidence = tuple(base.evidence) + tuple(acceptance.evidence)
        if base.passed and acceptance.passed:
            return Evaluation(True, evidence, f"{base.reason}; {acceptance.reason}")
        reasons = [reason for passed, reason in ((base.passed, base.reason), (acceptance.passed, acceptance.reason)) if not passed]
        return Evaluation(False, evidence, "; ".join(reasons))

    def _discard_late_result(
        self, run_id: str, task_id: str, attempt_id: str, error: str | None = None
    ) -> None:
        run = self.store.get_run(run_id)
        if run is not None:
            for relative_path in self.store.discard_attempt_outputs(run_id, task_id, attempt_id):
                path = (Path(run.workspace) / relative_path).resolve(strict=False)
                try:
                    path.relative_to(Path(run.workspace).resolve())
                    path.unlink(missing_ok=True)
                except (OSError, ValueError):
                    # The ledger is authoritative; a file disappearing concurrently is harmless.
                    pass
        self.store.append_event(
            run_id,
            "task_result_discarded",
            {
                "attempt_id": attempt_id,
                "reason": "run_cancelled_or_task_no_longer_running",
                "error": error,
            },
            task_id=task_id,
        )

    def _build_task_prompt(self, run: Run, task: Any) -> str:
        dependencies = self.store.dependency_artifacts(task.id)
        if not dependencies:
            return task.prompt
        sections = [task.prompt, "", "Verified dependency artifacts (run-relative paths):"]
        for artifact in dependencies:
            relative = str(artifact["path"])
            sections.append(f"- task {artifact['task_id']}: {relative}")
            artifact_path = Path(run.workspace) / relative
            if artifact_path.is_file() and artifact_path.stat().st_size <= 20_000:
                try:
                    content = artifact_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = "<binary artifact; read it from the path>"
                sections.extend(["  preview:", content[:8_000]])
        return "\n".join(sections)

    @staticmethod
    def _runtime_artifact_path(task_root: Path, relative_path: str) -> Path:
        candidate = (task_root / relative_path).resolve(strict=False)
        try:
            candidate.relative_to(task_root.resolve())
        except ValueError as exc:
            raise ArtifactError(f"runtime artifact escapes task workspace: {relative_path}") from exc
        return candidate

    @staticmethod
    def _terminate_process_group(pid: int | None, pgid: int | None) -> None:
        if not pid or pid <= 1 or pid == os.getpid():
            return
        try:
            current_pgid = os.getpgrp()
        except OSError:
            current_pgid = None
        if pgid and pgid > 1 and pgid != current_pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
                return
            except (ProcessLookupError, PermissionError):
                pass
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def _can_retry(self, attempts_after_current: int) -> bool:
        return attempts_after_current < self.config.max_retries

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        if isinstance(error, RuntimeExecutionError):
            return str(error)[-2000:]
        return f"{type(error).__name__}: {str(error)[-1800:]}"
