"""Deterministic tests for one automatic solve execution deadline."""

from __future__ import annotations

import pytest

from lunar_evolution.automatic_solve_lifecycle import (
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


def test_owner_excludes_another_process_and_releases_workspace_lock(tmp_path) -> None:
    import subprocess
    import sys

    program = """
import sys
from pathlib import Path
from lunar_evolution.automatic_solve_lifecycle import own_automatic_solve, AutomaticSolveAlreadyRunning
try:
    with own_automatic_solve('parent', Path(sys.argv[1])):
        pass
except AutomaticSolveAlreadyRunning:
    sys.exit(3)
"""
    def probe():
        return subprocess.run([sys.executable, "-c", program, str(tmp_path)], timeout=10, check=False).returncode

    with own_automatic_solve("parent", tmp_path):
        assert probe() == 3
    assert probe() == 0


def test_workspace_lock_rejects_symlink_without_touching_target(tmp_path) -> None:
    target = tmp_path / "untouched"
    target.write_bytes(b"original")
    (tmp_path / ".automatic-solve.lock").symlink_to(target)
    with pytest.raises(OSError), own_automatic_solve("parent", tmp_path):
        pytest.fail("unsafe owner admitted")
    assert target.read_bytes() == b"original"
    with own_automatic_solve("parent"):
        pass


def test_budget_wins_between_last_task_success_and_parent_settlement(tmp_path) -> None:
    from lunar_evolution.models import RunStatus
    from lunar_evolution.store import Store

    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("solve", tmp_path / "run")
    task = store.ensure_orchestration_task(run.id, title="solve", prompt="deliver")
    store.supersede_pending_tasks(run.id, "automatic handoff")
    attempt = store.claim_orchestration_task(task.id, "automatic-solve")
    assert attempt is not None
    assert store.finish_task(task.id, attempt.id, True)
    assert store.fail_budget(run.id, "solve_wall_timeout", 10, 10, "expired")
    assert store.settle_run(run.id).status == RunStatus.FAILED
    assert not store.cancel_run(run.id)
    assert not store.fail_budget(run.id, "solve_wall_timeout", 20, 10, "expired")
    assert len([e for e in store.list_events(run.id) if e["type"] == "budget_exceeded"]) == 1
