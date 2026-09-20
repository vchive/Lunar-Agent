"""Provider-neutral, locally persisted worker sessions.

This layer is intentionally smaller than the task scheduler. It supplies the WebAgent-style
worker control plane (dispatch/send/list/wait/resume/cancel) while delegating execution to the
existing explicit AgentAdapter registry.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .agents import AgentAdapter, AgentRegistry, AgentRequest, AgentResult
from .models import Worker, WorkerOutcome, WorkerPhase, WorkerStopReason
from .store import Store

_MAX_INLINE_RESULT_BYTES = 64 * 1024
_MAX_ARTIFACT_READ_BYTES = 8 * 1024 * 1024
_RESULT_REF_PATTERN = re.compile(r"^worker-result-(worker-attempt-[0-9a-f]{32})-([0-9a-f]{64})$")


def _is_timeout_error(error: BaseException) -> bool:
    """Recognize typed timeout causes without persisting provider or exception text."""
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, TimeoutError) or type(current).__name__ == "TimeoutExpired":
            return True
        evidence = getattr(current, "evidence", None)
        if getattr(evidence, "reason", None) == "transport_timeout":
            return True
        current = current.__cause__ or current.__context__
    return False


class WorkerService:
    """Own worker execution handles and persist every lifecycle transition in ``Store``."""

    def __init__(
        self,
        store: Store,
        registry: AgentRegistry,
        workspace: str | Path,
        *,
        max_depth: int = 1,
        max_workers: int = 4,
    ) -> None:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        self.store = store
        self.registry = registry
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.max_depth = max_depth
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lunar-worker")
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._waiters: dict[str, int] = {}
        self._active: dict[str, tuple[AgentAdapter, str]] = {}
        self._futures: dict[str, Future[None]] = {}
        self.store.reconcile_workers()

    def dispatch(
        self,
        owner_id: str,
        *,
        role: str = "worker",
        prompt: str,
        description: str | None = None,
        parent_worker_id: str | None = None,
        required_capabilities: Sequence[str] = (),
        preferred_adapter: str | None = None,
        timeout: float | None = None,
    ) -> Worker:
        selected = self.registry.select(role, required_capabilities, preferred_adapter)
        worker = self.store.create_worker(
            owner_id,
            role,
            description or prompt[:512],
            parent_worker_id=parent_worker_id,
            agent_type=selected.name,
            max_depth=self.max_depth,
        )
        return self._start(worker, owner_id, prompt, required_capabilities, preferred_adapter, timeout)

    def send(self, owner_id: str, worker_id: str, content: str) -> Worker:
        worker = self._owned(owner_id, worker_id)
        if worker.phase is not WorkerPhase.RUNNING:
            raise ValueError("worker is not running")
        self.store.append_worker_input(worker_id, owner_id, content)
        return self.store.get_worker(worker_id) or worker

    def list(self, owner_id: str, *, running_only: bool = False) -> list[Worker]:
        return self.store.list_workers(owner_id, phase=WorkerPhase.RUNNING if running_only else None)

    def wait(self, owner_id: str, worker_id: str, timeout: float | None = None) -> Worker:
        self._owned(owner_id, worker_id)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._waiters[worker_id] = self._waiters.get(worker_id, 0) + 1
            try:
                while True:
                    worker = self._owned(owner_id, worker_id)
                    if worker.phase is WorkerPhase.IDLE:
                        return worker
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return worker
                    self._condition.wait(remaining)
            finally:
                count = self._waiters.get(worker_id, 1) - 1
                if count:
                    self._waiters[worker_id] = count
                else:
                    self._waiters.pop(worker_id, None)

    def cancel(self, owner_id: str, worker_id: str) -> Worker:
        self._owned(owner_id, worker_id)
        ids = self.store.cancel_worker_tree(worker_id, owner_id)
        with self._lock:
            adapters = [self._active.get(item, (None, ""))[0] for item in ids]
        seen: set[int] = set()
        for adapter in adapters:
            if adapter is None or id(adapter) in seen:
                continue
            seen.add(id(adapter))
            try:
                adapter.cancel()
            except Exception:  # noqa: BLE001, S112 - cleanup continues for every owned adapter
                continue
        with self._condition:
            self._condition.notify_all()
        return self.store.get_worker(worker_id)  # type: ignore[return-value]

    def resume(
        self,
        owner_id: str,
        worker_id: str,
        *,
        prompt: str | None = None,
        required_capabilities: Sequence[str] = (),
        preferred_adapter: str | None = None,
        timeout: float | None = None,
    ) -> Worker:
        worker = self._owned(owner_id, worker_id)
        if worker.phase.value == "running":
            raise ValueError("worker is already running")
        self.registry.select(worker.role, required_capabilities, preferred_adapter)
        queued = self.store.list_worker_inputs(worker_id)
        prior = self.store.list_worker_attempts(worker_id, owner_id)
        effective = prompt or (prior[-1].prompt if prior else worker.description)
        if queued:
            effective = effective + "\n\nFollow-up input:\n" + "\n\n".join(queued)
        resumed = self._start(worker, owner_id, effective, required_capabilities, preferred_adapter, timeout)
        if queued:
            self.store.list_worker_inputs(worker_id, consume=True)
        return resumed

    def reconcile(self) -> int:
        return self.store.reconcile_workers()

    def read_result(self, owner_id: str, worker_id: str) -> str | None:
        """Read and verify a large result artifact owned by the caller."""
        worker = self._owned(owner_id, worker_id)
        if worker.result_ref is None:
            return worker.result
        match = _RESULT_REF_PATTERN.fullmatch(worker.result_ref)
        if match is None:
            raise ValueError("worker result reference is invalid")
        attempt_id, expected_digest = match.groups()
        if not any(attempt.id == attempt_id for attempt in self.store.list_worker_attempts(worker_id, owner_id)):
            raise ValueError("worker result attempt is unknown")
        path = self.workspace / "workers" / worker.id / attempt_id / "result.txt"
        resolved = path.resolve(strict=False)
        artifact_root = (self.workspace / "workers").resolve(strict=False)
        try:
            resolved.relative_to(artifact_root)
        except ValueError as exc:
            raise ValueError("worker result artifact escapes workspace") from exc
        if path.is_symlink() or not path.is_file():
            raise ValueError("worker result artifact is missing")
        raw = path.read_bytes()
        if len(raw) > _MAX_ARTIFACT_READ_BYTES:
            raise ValueError("worker result artifact exceeds the read limit")
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("worker result artifact integrity check failed")
        return raw.decode("utf-8")

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _start(
        self,
        worker: Worker,
        owner_id: str,
        prompt: str,
        required_capabilities: Sequence[str],
        preferred_adapter: str | None,
        timeout: float | None,
    ) -> Worker:
        adapter = self.registry.select(worker.role, required_capabilities, preferred_adapter)
        attempt = self.store.start_worker_attempt(worker.id, owner_id, prompt)
        with self._lock:
            self._active[worker.id] = (adapter, attempt.id)
            try:
                self._futures[worker.id] = self._executor.submit(
                    self._execute, worker, attempt.id, adapter, prompt, required_capabilities, timeout
                )
            except Exception:
                self._active.pop(worker.id, None)
                self.store.settle_worker(
                    worker.id,
                    attempt.id,
                    WorkerOutcome.FAILURE,
                    reason=WorkerStopReason.RUNTIME_ERROR,
                )
                raise
        return self.store.get_worker(worker.id)  # type: ignore[return-value]

    def _execute(
        self,
        worker: Worker,
        attempt_id: str,
        adapter: AgentAdapter,
        prompt: str,
        required_capabilities: Sequence[str],
        timeout: float | None,
    ) -> None:
        root = self.workspace / "workers" / worker.id / attempt_id
        root.mkdir(parents=True, exist_ok=True)
        request = AgentRequest(
            run_id=f"worker-run-{worker.id}", task_id=attempt_id, role=worker.role,
            prompt=prompt, required_capabilities=tuple(required_capabilities), workspace=root, timeout=timeout,
        )
        try:
            result: AgentResult = adapter.run(request)
            outcome = WorkerOutcome.SUCCESS if result.status == "succeeded" else WorkerOutcome.STOPPED if result.status == "cancelled" else WorkerOutcome.FAILURE
            reason = WorkerStopReason.CANCELLED if result.status == "cancelled" else WorkerStopReason.RUNTIME_ERROR if result.status == "failed" else None
            with self._condition:
                delivery = "waiter" if self._waiters.get(worker.id, 0) else "notification"
            result_ref = None
            encoded_result = result.text.encode("utf-8")
            if len(encoded_result) > _MAX_INLINE_RESULT_BYTES:
                (root / "result.txt").write_bytes(encoded_result)
                result_ref = f"worker-result-{attempt_id}-{hashlib.sha256(encoded_result).hexdigest()}"
            self.store.settle_worker(
                worker.id,
                attempt_id,
                outcome,
                result=result.text,
                result_ref=result_ref,
                reason=reason,
                delivery=delivery,
            )
        except Exception as exc:  # noqa: BLE001 - persist a safe typed failure for every adapter error
            reason = WorkerStopReason.TIMEOUT if _is_timeout_error(exc) else WorkerStopReason.RUNTIME_ERROR
            self.store.settle_worker(worker.id, attempt_id, WorkerOutcome.FAILURE, reason=reason)
        finally:
            with self._condition:
                self._active.pop(worker.id, None)
                self._futures.pop(worker.id, None)
                self._condition.notify_all()

    def _owned(self, owner_id: str, worker_id: str) -> Worker:
        worker = self.store.get_worker(worker_id)
        if worker is None:
            raise ValueError(f"unknown worker: {worker_id}")
        if worker.owner_id != owner_id:
            raise PermissionError("worker is not owned by caller")
        return worker
