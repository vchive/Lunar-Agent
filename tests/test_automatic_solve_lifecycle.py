"""Deterministic tests for one automatic solve execution deadline."""

from __future__ import annotations

import pytest

from famou.automatic_solve_lifecycle import (
    AutomaticSolveAlreadyRunning,
    AutomaticSolveExecutionOwner,
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
    own_automatic_solve,
)


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_remaining_uses_one_fixed_deadline_across_phases() -> None:
    clock = FakeClock()
    control = SolveExecutionControl(10, clock=clock)

    assert control.started_at == 100.0
    assert control.deadline == 110.0
    assert control.remaining() == 10.0

    clock.value = 103.0
    assert control.remaining() == 7.0
    assert control.effective_timeout(30, stage="generation") == 7.0

    clock.value = 106.0
    assert control.remaining(stage_timeout=2) == 2.0
    assert control.effective_timeout(30, stage="delivery") == 4.0
    assert control.deadline == 110.0


def test_expiry_rejects_new_work_and_reports_stage() -> None:
    clock = FakeClock()
    control = SolveExecutionControl(5, clock=clock)
    clock.value = 105.0

    assert control.remaining() == 0.0
    with pytest.raises(SolveExecutionBudgetExceeded) as raised:
        control.check("scoring")
    assert raised.value.stage == "scoring"
    assert raised.value.limit == "solve_wall_timeout"
    assert raised.value.maximum == 5.0


def test_cancellation_is_composable_and_wins_over_remaining_budget() -> None:
    clock = FakeClock()
    parent_cancelled = False
    child_cancelled = False
    control = SolveExecutionControl(
        20,
        clock=clock,
        cancellation_callbacks=(lambda: parent_cancelled, ),
    )
    control.add_cancellation_callback(lambda: child_cancelled)

    assert control.check("contract") == 20.0
    parent_cancelled = True
    assert control.remaining() == 0.0
    with pytest.raises(SolveExecutionCancelled) as raised:
        control.check("candidate")
    assert raised.value.stage == "candidate"

    parent_cancelled = False
    child_cancelled = True
    with pytest.raises(SolveExecutionCancelled):
        control.effective_timeout(5, stage="delivery")


def test_local_cancel_does_not_change_deadline() -> None:
    clock = FakeClock()
    control = SolveExecutionControl(20, clock=clock)
    control.cancel()

    assert control.deadline == 120.0
    assert control.remaining() == 0.0
    with pytest.raises(SolveExecutionCancelled):
        control.check("preparation")


@pytest.mark.parametrize("ceiling", [0, -1, float("inf"), float("nan"), True])
def test_stage_timeout_must_be_positive_and_finite(ceiling: object) -> None:
    control = SolveExecutionControl(10, clock=FakeClock())
    with pytest.raises((TypeError, ValueError)):
        control.remaining(ceiling)


def test_explicit_start_time_avoids_resetting_deadline() -> None:
    clock = FakeClock(500.0)
    control = SolveExecutionControl(10, clock=clock, started_at=25.0)

    assert control.started_at == 25.0
    assert control.deadline == 35.0
    assert control.remaining() == 0.0


def test_owner_is_exclusive_and_releases_after_context() -> None:
    first = AutomaticSolveExecutionOwner("parent")
    first.acquire()
    try:
        with pytest.raises(AutomaticSolveAlreadyRunning):
            AutomaticSolveExecutionOwner("parent").acquire()
    finally:
        first.release()
    with own_automatic_solve("parent"), pytest.raises(AutomaticSolveAlreadyRunning):
        AutomaticSolveExecutionOwner("parent").acquire()
    with own_automatic_solve("parent"):
        pass
