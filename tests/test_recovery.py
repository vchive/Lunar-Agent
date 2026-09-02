import json
from pathlib import Path

from famou.agent_loop import AgentInputRequired
from famou.budget import BudgetSpec
from famou.config import Config
from famou.controller import LocalController
from famou.policy import PlanDocument, PlanTask
from famou.runtime import MockRuntime, RuntimeExecutionError, RuntimeResult


class InputRuntime:
    name = "input"

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, workspace, timeout
        raise AgentInputRequired("Which report format should I use?", ("json", "markdown"))

    def cancel(self) -> None:
        return None


class ConfigurationFailureRuntime:
    name = "configuration-failure"

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, workspace, timeout
        raise RuntimeExecutionError(
            "could not start runtime: api_key=secret-value command not found: private-agent"
        )

    def cancel(self) -> None:
        return None


class UnclassifiedFailureRuntime:
    name = "unclassified-failure"

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, workspace, timeout
        raise RuntimeExecutionError("runtime exited with code 1")

    def cancel(self) -> None:
        return None


def _acceptance_document() -> PlanDocument:
    return PlanDocument(
        goal="write a verified report",
        plan_id="recovery-report-plan",
        tasks=(
            PlanTask(
                "report",
                "Report",
                "Write a report.json artifact",
                acceptance={"artifact_exists": "report.json"},
            ),
        ),
    )


def test_failed_acceptance_proposes_patch_and_is_idempotently_audited(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou", max_retries=1), MockRuntime())
    run = controller.start_plan(_acceptance_document())
    before = controller.store.get_current_plan(run.id)

    proposal = controller.recover(run.id)

    assert proposal.action == "propose_patch"
    assert proposal.plan_id == "recovery-report-plan"
    assert proposal.plan_version == 1
    assert proposal.plan_task_id == "report"
    assert proposal.guidance == {
        "required_operation": "update_task",
        "target": "report",
        "inspect": ["evaluation"],
    }
    assert "acceptance:artifact_exists" in proposal.evidence
    assert proposal.artifact_path is not None
    artifact = run.workspace / proposal.artifact_path
    assert json.loads(artifact.read_text(encoding="utf-8"))["action"] == "propose_patch"

    repeated = controller.recover(run.id)
    events = [event for event in controller.store.list_events(run.id) if event["type"] == "recovery_proposed"]
    artifacts = [item for item in controller.store.list_artifacts(run.id) if item["kind"] == "recovery"]
    after = controller.store.get_current_plan(run.id)
    assert repeated.to_dict() == proposal.to_dict()
    assert len(events) == 1
    assert len(artifacts) == 1
    assert before == after


def test_waiting_input_proposes_ask_user_without_executing_a_new_attempt(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), InputRuntime())
    run = controller.start("need a decision")
    task = controller.store.list_tasks(run.id)[0]

    proposal = controller.recover(run.id)

    assert run.status.value == "awaiting_input"
    assert proposal.action == "ask_user"
    assert proposal.guidance == {"input_request": True}
    assert proposal.questions == ("Answer the pending input request before resuming this run.",)
    assert controller.store.get_task(task.id).attempts == 1  # type: ignore[union-attr]


def test_configuration_failure_requests_explicit_configuration_without_copying_error(tmp_path: Path) -> None:
    controller = LocalController(
        Config(tmp_path / ".famou", max_retries=1), ConfigurationFailureRuntime()
    )
    run = controller.start("run the external agent")

    proposal = controller.recover(run.id)
    encoded = json.dumps(proposal.to_dict())

    assert proposal.action == "ask_user"
    assert proposal.guidance == {"runtime_configuration": True}
    assert "private-agent" not in encoded
    assert "secret-value" not in encoded
    assert proposal.questions == (
        "Provide or confirm the runtime configuration and authority required to continue.",
    )


def test_budget_failure_proposes_replan_without_relaxing_the_budget(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    document = PlanDocument(
        goal="two bounded tasks",
        plan_id="budget-recovery-plan",
        budget=BudgetSpec(max_tasks=1),
        tasks=(PlanTask("one", "One", "one"), PlanTask("two", "Two", "two")),
    )
    run = controller.start_plan(document)

    proposal = controller.recover(run.id)
    current = controller.store.get_current_plan(run.id)

    assert run.status.value == "failed"
    assert proposal.action == "propose_replan"
    assert proposal.guidance == {"preserve_verified_artifacts": True, "inspect": ["budget"]}
    assert "budget:max_tasks" in proposal.evidence
    assert current is not None and current.budget.max_tasks == 1


def test_unclassified_runtime_failure_after_retries_proposes_replan(tmp_path: Path) -> None:
    controller = LocalController(
        Config(tmp_path / ".famou", max_retries=1), UnclassifiedFailureRuntime()
    )
    run = controller.start_plan(
        PlanDocument(
            goal="run a configured task",
            plan_id="runtime-recovery-plan",
            tasks=(PlanTask("execute", "Execute", "execute"),),
        )
    )

    proposal = controller.recover(run.id)

    assert proposal.action == "propose_replan"
    assert proposal.guidance == {"preserve_verified_artifacts": True, "inspect": ["failed_tasks"]}
    assert "runtime exited" not in json.dumps(proposal.to_dict())


def test_active_uncertain_work_proposes_retry_and_terminal_runs_are_noops(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    pending = controller.create("recover interrupted work")
    task = controller.store.list_tasks(pending.id)[0]
    controller.store.claim_task(task.id, "fixture")
    controller.store.recover_running(pending.id)
    controller.store.settle_run(pending.id)

    retry = controller.recover(pending.id)
    assert retry.action == "retry"
    assert retry.guidance == {"command": "resume"}

    successful = controller.start("finish normally")
    none = controller.recover(successful.id)
    assert none.action == "none"
    assert none.guidance == {}

    interrupted = controller.create("cancel safely")
    assert controller.cancel(interrupted.id)
    stop = controller.recover(interrupted.id)
    assert stop.action == "stop"
    assert stop.guidance == {"terminal": True}
