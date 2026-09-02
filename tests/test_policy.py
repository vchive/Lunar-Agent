from pathlib import Path

import pytest

from famou.config import Config
from famou.controller import LocalController
from famou.policy import MasterPolicy, PlanDocument, PlanPatch, PlanTask, apply_patch
from famou.runtime import MockRuntime
from famou.store import Store


def _document() -> PlanDocument:
    return PlanDocument(
        goal="prepare and verify a report",
        plan_id="plan-report",
        tasks=(
            PlanTask("research", "Research", "Collect facts"),
            PlanTask("write", "Write", "Draft report", ("research",)),
        ),
        hard_constraints=("keep files local",),
        verification={"required": True},
        delivery={"artifacts": True},
    )


def test_master_policy_uses_smallest_useful_action() -> None:
    policy = MasterPolicy()
    direct = policy.decide("What does SQLite WAL mode provide?")
    complex_goal = policy.decide("Prepare a report and verify its files in multiple steps")
    question = policy.decide("Please ask me because missing information changes the result")

    assert direct.action == "answer" and direct.plan_id is None
    assert complex_goal.action == "execute_plan" and complex_goal.plan_id is not None
    assert complex_goal.plan is not None and complex_goal.plan["tasks"][0]["id"] == "execute"
    assert question.action == "ask_user" and len(question.questions) == 1


def test_plan_document_rejects_cycle_and_secret() -> None:
    with pytest.raises(ValueError, match="cycle"):
        PlanDocument(
            goal="bad",
            plan_id="plan-bad",
            tasks=(PlanTask("a", "A", "a", ("b",)), PlanTask("b", "B", "b", ("a",))),
        )
    with pytest.raises(ValueError, match="credential"):
        PlanDocument(goal="sk-abcdefghijklmnop", plan_id="plan-secret", tasks=(PlanTask("a", "A", "a"),))


def test_patch_creates_immutable_valid_next_revision() -> None:
    current = _document()
    patch = PlanPatch(
        plan_id=current.plan_id,
        base_version=1,
        reason="need a verification task",
        operations=(
            {
                "op": "add_task",
                "task": {"id": "check", "title": "Check", "prompt": "Verify output", "depends_on": ["write"]},
            },
        ),
        evidence=("new evaluator requirement",),
    )
    updated = apply_patch(current, patch)
    assert current.version == 1
    assert updated.version == 2 and updated.parent_version == 1
    assert [task.id for task in updated.tasks] == ["research", "write", "check"]
    with pytest.raises(ValueError, match="does not match"):
        apply_patch(updated, patch)


def test_planned_run_persists_revision_and_physical_task_mapping(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run_with_plan(_document())
    current = store.get_current_plan(run.id)
    tasks = store.list_tasks(run.id)

    assert current is not None and current.plan_id == "plan-report" and current.version == 1
    assert {task.plan_task_id for task in tasks} == {"research", "write"}
    assert all(task.id != task.plan_task_id for task in tasks)
    assert tasks[1].dependencies == (tasks[0].id,)


def test_stale_patch_is_atomic_and_current_plan_survives_restart(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run_with_plan(_document())
    patch = PlanPatch(
        plan_id="plan-report",
        base_version=1,
        reason="add check",
        operations=(
            {"op": "add_task", "task": {"id": "check", "title": "Check", "prompt": "Check", "depends_on": ["write"]}},
        ),
    )
    updated = store.patch_plan(run.id, patch)
    assert updated.version == 2
    with pytest.raises(ValueError, match="does not match"):
        store.patch_plan(run.id, patch)

    reopened = Store(tmp_path / "state.db")
    reopened.initialize()
    restored = reopened.get_current_plan(run.id)
    assert restored is not None and restored.version == 2
    assert len(reopened.list_plan_revisions(run.id)) == 2


def test_controller_delivers_only_verified_planned_results(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.start_plan(_document())
    decision = controller.deliver(run.id)
    assert run.status.value == "succeeded"
    assert decision.action == "deliver"
    assert decision.evidence


def test_delivery_rejects_a_failed_evaluation(tmp_path: Path) -> None:
    class RejectingEvaluator:
        def evaluate(self, result: str, workspace: Path):
            del result, workspace
            from famou.evaluator import Evaluation

            return Evaluation(False, ("fixture rejection",), "rejected")

    controller = LocalController(
        Config(tmp_path / ".famou", max_retries=1), MockRuntime(), evaluator=RejectingEvaluator()
    )
    run = controller.start_plan(_document())
    assert run.status.value == "failed"
    with pytest.raises(ValueError, match="fully verified"):
        controller.deliver(run.id)
