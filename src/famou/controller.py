"""Durable orchestration loop for the standalone local agent."""

from __future__ import annotations

from pathlib import Path

from .artifacts import ArtifactStore
from .config import Config
from .evaluator import Evaluator, NonEmptyEvaluator
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

    def start(self, goal: str) -> Run:
        run = self.create(goal)
        return self.resume(run.id)

    def create(self, goal: str) -> Run:
        """Persist a run and its initial task without executing it."""
        run = self.store.create_run(goal)
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
        while True:
            task = self.store.next_task(run_id)
            if task is None:
                break
            attempt = self.store.claim_task(task.id, self.runtime.name)
            if attempt is None:
                continue
            task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
            artifacts = ArtifactStore(run.workspace, self.store, run_id)
            artifacts.write_text(
                f"tasks/{task.id}/{attempt.id}/prompt.md",
                task.prompt,
                task.id,
                kind="prompt",
            )
            try:
                result = self.runtime.run(task.prompt, task_root, self.config.runtime_timeout)
                result_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/result.txt",
                    result.text,
                    task.id,
                )
                for relative_path in result.artifacts:
                    runtime_path = (task_root / relative_path).absolute()
                    artifacts.record(runtime_path, task.id, kind="runtime")
                evaluation = self.evaluator.evaluate(result.text, task_root)
                self.store.append_event(
                    run_id,
                    "task_evaluated",
                    {
                        "attempt_id": attempt.id,
                        "passed": evaluation.passed,
                        "reason": evaluation.reason,
                        "evidence": list(evaluation.evidence),
                    },
                    task_id=task.id,
                )
                relative_result = str(result_path.relative_to(Path(run.workspace)))
                if evaluation.passed:
                    self.store.finish_task(task.id, attempt.id, True, relative_result)
                elif self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, evaluation.reason)
                else:
                    self.store.finish_task(task.id, attempt.id, False, relative_result, evaluation.reason)
            except Exception as exc:  # noqa: BLE001 - runtime boundary must persist all failures
                error = self._sanitize_error(exc)
                if self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
        settled = self.store.settle_run(run_id)
        assert settled is not None
        return settled

    def cancel(self, run_id: str) -> bool:
        cancelled = self.store.cancel_run(run_id)
        if cancelled:
            self.runtime.cancel()
        return cancelled

    def _can_retry(self, attempts_after_current: int) -> bool:
        return attempts_after_current < self.config.max_retries

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        if isinstance(error, RuntimeExecutionError):
            return str(error)[-2000:]
        return f"{type(error).__name__}: {str(error)[-1800:]}"
