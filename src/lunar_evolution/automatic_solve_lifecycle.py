"""Process-local control for one automatic solve execution.

The solve wall budget is an operational deadline.  It is intentionally kept out of the
persisted input/profile/plan identities: callers create one control object after execution
admission and pass its remaining time to each bounded operation.
"""

from __future__ import annotations

import fcntl
import math
import os
import re
import stat
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import ClassVar, Final, Self

from .budget import BudgetExceeded

Clock = Callable[[], float]
CancellationCallback = Callable[[], bool]

_DEFAULT_STAGE: Final[str] = "solve"


class SolveExecutionBudgetExceeded(BudgetExceeded, TimeoutError):
    """The fixed active-execution solve deadline has no positive remainder."""

    def __init__(
        self,
        stage: str,
        *,
        started_at: float,
        deadline: float,
        observed_at: float,
    ) -> None:
        self.stage = _stage_name(stage)
        self.started_at = float(started_at)
        self.deadline = float(deadline)
        self.observed_at = float(observed_at)
        self.remaining_seconds = max(0.0, self.deadline - self.observed_at)
        elapsed = max(0.0, self.observed_at - self.started_at)
        maximum = max(0.0, self.deadline - self.started_at)
        # Keep the existing budget failure shape so Store.fail_budget can classify this
        # independently from BudgetSpec.max_runtime_seconds.
        super().__init__("solve_wall_timeout", max(elapsed, maximum), maximum)


class SolveExecutionCancelled(RuntimeError):
    """A parent, child, or run cancellation prevents new solve work."""

    def __init__(self, stage: str) -> None:
        self.stage = _stage_name(stage)
        super().__init__("automatic solve execution cancelled")


# These aliases keep the boundary easy to discover for callers that refer to the policy as a
# lifecycle or wall timeout.  They are aliases rather than subclasses so exception matching stays
# unambiguous.
AutomaticSolveTimeout = SolveExecutionBudgetExceeded
SolveLifecycleTimeout = SolveExecutionBudgetExceeded
AutomaticSolveCancelled = SolveExecutionCancelled
SolveLifecycleCancelled = SolveExecutionCancelled


class SolveExecutionControl:
    """A fixed monotonic deadline shared by every phase of one active solve.

    ``remaining`` never creates or extends a deadline.  It returns the positive remainder clipped
    to an optional existing stage ceiling, or ``0.0`` when the solve is cancelled or expired.
    Callers that are about to admit work should use ``check`` (or ``effective_timeout``), which
    raises a typed exception when no work may start.
    """

    def __init__(
        self,
        timeout_seconds: float,
        *,
        clock: Clock | None = None,
        started_at: float | None = None,
        cancellation_callbacks: Iterable[CancellationCallback] = (),
        cancelled: CancellationCallback | None = None,
        observe_stage: Callable[[str], None] | None = None,
    ) -> None:
        self.timeout_seconds = _positive_timeout(timeout_seconds, "solve wall timeout")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = time.monotonic if clock is None else clock
        self.started_at = _finite_time(self._clock() if started_at is None else started_at, "started_at")
        self.deadline = self.started_at + self.timeout_seconds
        callbacks = list(cancellation_callbacks)
        if cancelled is not None:
            callbacks.append(cancelled)
        if any(not callable(callback) for callback in callbacks):
            raise TypeError("cancellation callbacks must be callable")
        self._cancellation_callbacks: list[CancellationCallback] = callbacks
        self._cancelled = False
        self._observe_stage = observe_stage
        self._lock = RLock()

    def add_cancellation_callback(self, callback: CancellationCallback) -> SolveExecutionControl:
        """Compose a parent/child/run cancellation predicate into this control."""

        if not callable(callback):
            raise TypeError("cancellation callback must be callable")
        with self._lock:
            self._cancellation_callbacks.append(callback)
        return self

    # Short aliases make the API convenient at the process/runtime boundary while retaining one
    # canonical method for documentation and callers that need a descriptive name.
    add_cancel_callback = add_cancellation_callback

    def cancel(self) -> None:
        """Locally stop admitting work, without changing the fixed deadline."""

        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        """Return whether any composed cancellation authority has stopped this execution."""

        with self._lock:
            if self._cancelled:
                return True
            callbacks = tuple(self._cancellation_callbacks)
        return any(bool(callback()) for callback in callbacks)

    def remaining(self, stage_timeout: float | None = None) -> float:
        """Return remaining seconds, narrowed by ``stage_timeout`` when supplied.

        A zero result is deliberately non-admitting.  Use ``check`` before starting work when a
        typed cancellation or budget exception is required.
        """

        ceiling = None if stage_timeout is None else _positive_timeout(stage_timeout, "stage timeout")
        if self.is_cancelled():
            return 0.0
        remainder = max(0.0, self.deadline - self._now())
        return remainder if ceiling is None else min(remainder, ceiling)

    def check(self, stage: str = _DEFAULT_STAGE) -> float:
        """Require positive budget and no cancellation before admitting a stage."""

        stage = _stage_name(stage)
        if self._observe_stage is not None:
            self._observe_stage(stage)
        if self.is_cancelled():
            raise SolveExecutionCancelled(stage)
        observed_at = self._now()
        remainder = self.deadline - observed_at
        if remainder <= 0:
            raise SolveExecutionBudgetExceeded(
                stage,
                started_at=self.started_at,
                deadline=self.deadline,
                observed_at=observed_at,
            )
        return remainder

    def effective_timeout(self, stage_timeout: float | None = None, *, stage: str = _DEFAULT_STAGE) -> float:
        """Return the positive minimum of the solve remainder and a stage ceiling."""

        remainder = self.check(stage)
        if stage_timeout is None:
            return remainder
        return min(remainder, _positive_timeout(stage_timeout, "stage timeout"))

    timeout_for = effective_timeout

    def _now(self) -> float:
        return _finite_time(self._clock(), "clock value")


class AutomaticSolveAlreadyRunning(RuntimeError):
    """The same automatic solve already has an active local execution owner."""


class AutomaticSolveExecutionOwner:
    """Process-local exclusive owner keyed by one automatic solve parent ID.

    The owner prevents two foreground continuations in the same process from issuing overlapping
    preparation/evolution work for one parent.  It is intentionally not durable; restart recovery
    remains governed by the Store's existing task and event evidence.
    """

    _registry_lock: ClassVar[RLock] = RLock()
    _active_parent_ids: ClassVar[set[str]] = set()

    def __init__(self, parent_id: str) -> None:
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise ValueError("parent_id must be a non-empty string")
        self.parent_id = parent_id
        self._held = False

    def acquire(self) -> Self:
        with self._registry_lock:
            if self.parent_id in self._active_parent_ids:
                raise AutomaticSolveAlreadyRunning(
                    "automatic solve already has an active execution owner"
                )
            self._active_parent_ids.add(self.parent_id)
            self._held = True
        return self

    def release(self) -> None:
        with self._registry_lock:
            if self._held:
                self._active_parent_ids.discard(self.parent_id)
                self._held = False

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        self.release()


@contextmanager
def own_automatic_solve(
    parent_id: str, workspace: Path | None = None,
) -> Iterator[AutomaticSolveExecutionOwner]:
    """Acquire and reliably release an active solve owner."""
    owner = AutomaticSolveExecutionOwner(parent_id)
    with owner:
        if workspace is None:
            yield owner
            return
        path = Path(workspace) / ".automatic-solve.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("invalid automatic solve ownership file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AutomaticSolveAlreadyRunning("automatic solve already has an active execution owner") from None
            named = path.lstat()
            if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
                raise ValueError("automatic solve ownership file changed")
            yield owner
        finally:
            os.close(fd)


_STAGES = frozenset({
    "contract", "preparation", "candidate_generation", "candidate_execution",
    "evaluation", "selection", "delivery", "solve",
})
_REASONS = frozenset({"completed", "cancelled", "solve_wall_timeout", "failed", "interrupted", "awaiting_input", "preparation_recoverable"})
_STATES = frozenset({"active", "awaiting_input", "terminal", "inactive"})


class SolveExecutionObservation:
    """Persist bounded observations; never serialize a process-local monotonic deadline."""

    def __init__(self, store, run_id: str, timeout: float | None) -> None:
        self.store, self.run_id = store, run_id
        self.execution_id = "solve-" + uuid.uuid4().hex
        self.timeout = timeout
        self.stage = "contract"
        self.state = None
        self.observe("contract")

    def observe(self, stage: str, *, state: str = "active", reason: str | None = None) -> None:
        stage = {"candidate_evaluation": "evaluation", "candidate_persistence": "selection",
                 "evolution": "selection", "generation": "candidate_generation"}.get(stage, stage)
        stage = stage if stage in _STAGES else "preparation"
        if state not in _STATES or reason is not None and reason not in _REASONS:
            raise ValueError("invalid solve observation")
        if (stage, state) == (self.stage, self.state):
            return
        self.stage, self.state = stage, state
        self.store.append_event(self.run_id, "solve_execution", {
            "schema_version": "1", "execution_id": self.execution_id,
            "scope": "active_execution", "policy_seconds": self.timeout,
            "policy_origin": "explicit" if self.timeout is not None else "absent",
            "stage": stage, "state": state, "stopping_reason": reason,
        })


def solve_execution_status(store, run) -> dict | None:
    """Read only fixed diagnostic fields, with terminal Store state taking precedence."""
    events = store.list_events(run.id)
    requests = [e.get("payload") for e in events if e.get("type") == "evolution_requested"]
    if not requests or not isinstance(requests[-1], dict) or requests[-1].get("automatic_lifecycle_version") != 1:
        return None
    payload = next((e.get("payload") for e in reversed(events) if e.get("type") == "solve_execution"), None)
    fields = {"schema_version", "execution_id", "scope", "policy_seconds", "policy_origin",
              "stage", "state", "stopping_reason"}
    if not isinstance(payload, dict) or not fields.issubset(payload):
        return None
    execution_id, timeout = payload.get("execution_id"), payload.get("policy_seconds")
    if (not isinstance(execution_id, str) or not re.fullmatch(r"solve-[0-9a-f]{32}", execution_id)
            or payload.get("schema_version") != "1" or payload.get("scope") != "active_execution"
            or not isinstance(payload.get("stage"), str) or not isinstance(payload.get("state"), str)
            or payload.get("stopping_reason") is not None and not isinstance(payload.get("stopping_reason"), str)
            or payload.get("stage") not in _STAGES or payload.get("state") not in _STATES
            or payload.get("stopping_reason") not in _REASONS | {None}
            or timeout is not None and (type(timeout) not in {int, float} or not 0 < timeout <= 86400)
            or payload.get("policy_origin") != ("explicit" if timeout is not None else "absent")
            or timeout != requests[-1].get("solve_wall_timeout")):
        return None
    result = {key: payload[key] for key in (
        "schema_version", "execution_id", "scope", "policy_seconds", "policy_origin",
        "stage", "state", "stopping_reason",
    )}
    if run.status.value in {"succeeded", "failed", "cancelled"}:
        result["state"] = "terminal"
        result["stopping_reason"] = {
            "succeeded": "completed", "cancelled": "cancelled", "failed": "failed",
        }[run.status.value]
        if run.status.value == "failed" and any(e.get("type") == "budget_exceeded"
                and isinstance(e.get("payload"), dict) and e["payload"].get("limit") == "solve_wall_timeout" for e in events):
            result["stopping_reason"] = "solve_wall_timeout"
    return result


def _positive_timeout(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be finite and positive")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return value


def _finite_time(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be finite")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _stage_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ValueError("stage must be a bounded non-empty string")
    return value.strip()


__all__ = [
    "AutomaticSolveAlreadyRunning",
    "AutomaticSolveCancelled",
    "AutomaticSolveExecutionOwner",
    "AutomaticSolveTimeout",
    "CancellationCallback",
    "Clock",
    "SolveExecutionBudgetExceeded",
    "SolveExecutionCancelled",
    "SolveExecutionControl",
    "SolveLifecycleCancelled",
    "SolveLifecycleTimeout",
    "own_automatic_solve",
]
