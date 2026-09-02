from pathlib import Path

from famou.config import Config
from famou.controller import LocalController
from famou.runtime import RuntimeExecutionError, RuntimeResult


class AcceptanceRetryRuntime:
    name = "acceptance-retry"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        self.prompts.append(prompt)
        workspace.mkdir(parents=True, exist_ok=True)
        if len(self.prompts) == 1:
            return RuntimeResult("first result")
        assert "acceptance_rule:artifact_exists" in prompt
        (workspace / "report.txt").write_text("verified", encoding="utf-8")
        return RuntimeResult("corrected result", artifacts=("report.txt",))

    def cancel(self) -> None:
        return None


class RuntimeFailureRetryRuntime:
    name = "runtime-failure-retry"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del workspace, timeout
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            raise RuntimeExecutionError("api_key=secret-value command not found: private-agent")
        assert "source: runtime_failure" in prompt
        return RuntimeResult("recovered result")

    def cancel(self) -> None:
        return None


def test_retry_prompt_contains_failed_acceptance_rule_and_preserves_original_prompt(
    tmp_path: Path,
) -> None:
    runtime = AcceptanceRetryRuntime()
    controller = LocalController(Config(tmp_path / ".famou", max_retries=2), runtime)
    run = controller.start(
        "verified retry",
        [
            {
                "id": "report",
                "prompt": "Create report.txt",
                "acceptance": {"artifact_exists": "report.txt"},
            }
        ],
    )

    assert run.status.value == "succeeded"
    assert len(runtime.prompts) == 2
    assert runtime.prompts[0] == "Create report.txt"
    assert runtime.prompts[1].startswith("Create report.txt\n\nRetry feedback")
    assert "source: evaluation" in runtime.prompts[1]
    assert "acceptance_rule:artifact_exists" in runtime.prompts[1]
    assert len(list(run.workspace.glob("tasks/report/*/prompt.md"))) == 2
    assert controller.store.get_current_plan(run.id) is None


def test_runtime_retry_feedback_is_generic_and_does_not_copy_raw_error(
    tmp_path: Path,
) -> None:
    runtime = RuntimeFailureRetryRuntime()
    controller = LocalController(Config(tmp_path / ".famou", max_retries=2), runtime)
    run = controller.start("runtime retry", [{"id": "task", "prompt": "Complete the task"}])

    assert run.status.value == "succeeded"
    assert len(runtime.prompts) == 2
    assert runtime.prompts[1].startswith("Complete the task\n\nRetry feedback")
    assert "runtime_failure" in runtime.prompts[1]
    assert "secret-value" not in runtime.prompts[1]
    prompt_files = list(run.workspace.glob("tasks/task/*/prompt.md"))
    assert len(prompt_files) == 2
    assert all("secret-value" not in path.read_text(encoding="utf-8") for path in prompt_files)


def test_retry_feedback_ignores_malformed_persisted_evidence(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou", max_retries=2), RuntimeFailureRetryRuntime())
    run = controller.create("malformed feedback", [{"id": "task", "prompt": "do it"}])
    task = controller.store.next_task(run.id)
    assert task is not None
    attempt = controller.store.claim_task(task.id, "fixture")
    assert attempt is not None
    controller.store.retry_task(task.id, attempt.id, "raw secret must remain outside prompt")
    controller.store.append_event(
        run.id,
        "task_evaluated",
        {
            "attempt_id": attempt.id,
            "passed": False,
            "details": {"acceptance": {"rule": "unknown", "passed": False}},
        },
        task_id=task.id,
    )
    retry_task = controller.store.next_task(run.id)
    assert retry_task is not None
    assert "source: evaluation" in controller._build_task_prompt(run, retry_task)
    assert "unknown" not in controller._build_task_prompt(run, retry_task)
