"""Process-local control for one automatic solve execution.

The solve wall budget is an operational deadline.  It is intentionally kept out of the
persisted input/profile/plan identities: callers create one control object after execution
admission and pass its remaining time to each bounded operation.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
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
def own_automatic_solve(parent_id: str) -> Iterator[AutomaticSolveExecutionOwner]:
    """Acquire and reliably release an active solve owner."""
    owner = AutomaticSolveExecutionOwner(parent_id)
    with owner:
        yield owner


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
