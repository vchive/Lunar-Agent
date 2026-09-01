import json
from pathlib import Path

from famou.agent_loop import AgentInputRequired, AgentLoopRuntime
from famou.artifacts import ArtifactStore
from famou.cli import main
from famou.config import Config
from famou.controller import LocalController
from famou.memory import MemoryStore
from famou.runtime import ModelTurn, ToolCall
from famou.store import Store
from famou.tools import LocalToolRegistry


class AskingModel:
    name = "asking-fixture"

    def __init__(self) -> None:
        self.turns = [
            ModelTurn(
                "",
                (ToolCall("ask-1", "ask_user", {"question": "Which format?", "options": ["csv", "json"]}),),
            ),
            ModelTurn("Used the selected format", ()),
        ]
        self.prompts: list[list[dict[str, object]]] = []

    def complete(self, messages, tools=(), timeout=None):
        del tools, timeout
        self.prompts.append(messages)
        return self.turns.pop(0)

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_ask_user_pauses_before_another_model_turn(tmp_path: Path) -> None:
    model = AskingModel()
    runtime = AgentLoopRuntime(model, tools=LocalToolRegistry(), max_steps=3)
    try:
        runtime.run("choose a format", tmp_path)
    except AgentInputRequired as exc:
        assert exc.question == "Which format?"
        assert exc.options == ("csv", "json")
    else:
        raise AssertionError("ask_user should pause the session")
    assert len(model.prompts) == 1


def test_controller_persists_input_and_resumes_same_task(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    model = AskingModel()
    controller = LocalController(
        config,
        AgentLoopRuntime(model, tools=LocalToolRegistry(), max_steps=3, session_history=True),
        memory=MemoryStore(config.database),
    )
    run = controller.start("choose a format")
    assert run.status.value == "awaiting_input"
    pending = controller.store.pending_input(run.id)
    assert pending is not None
    assert pending["question"] == "Which format?"
    assert pending["options"] == ["csv", "json"]
    assert (run.workspace / pending["request_path"]).is_file()
    assert any(item["kind"] == "session" for item in controller.store.list_artifacts(run.id))

    artifacts = ArtifactStore(run.workspace, controller.store, run.id)
    answer_path = artifacts.write_text(
        "tasks/" + pending["task_id"] + "/input-answer.json",
        json.dumps({"answer": "json"}) + "\n",
        pending["task_id"],
        kind="input",
    )
    task_id = controller.store.answer_input(
        run.id, str(answer_path.relative_to(run.workspace))
    )
    assert task_id == pending["task_id"]

    resumed = controller.resume(run.id)
    assert resumed.status.value == "succeeded"
    assert "json" in str(model.prompts[-1])
    assert len(controller.store.list_tasks(run.id)) == 1


def test_status_exposes_pending_input(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("question")
    task = store.next_task(run.id)
    assert task is not None
    attempt = store.claim_task(task.id, "fixture")
    assert attempt is not None
    assert store.await_input(task.id, attempt.id, "tasks/request.json", "Need a choice", ["a"])
    pending = store.pending_input(run.id)
    assert pending == {
        "run_id": run.id,
        "task_id": task.id,
        "question": "Need a choice",
        "options": ["a"],
        "request_path": None,
        "answer_path": None,
    }


def test_cli_answer_persists_artifact_and_resumes_same_run(tmp_path: Path, capsys) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("question")
    task = store.next_task(run.id)
    assert task is not None
    attempt = store.claim_task(task.id, "fixture")
    assert attempt is not None
    assert store.await_input(task.id, attempt.id, "tasks/request.json", "Need a choice", ["a"])

    assert main(["status", run.id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["run"]["status"] == "awaiting_input"
    assert status["input_request"]["question"] == "Need a choice"

    assert (
        main(
            [
                "answer",
                run.id,
                "a",
                "--runtime",
                "mock",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    answer_payload = json.loads(capsys.readouterr().out)
    assert answer_payload["run_id"] == run.id
    assert answer_payload["status"] == "succeeded"
    assert store.list_tasks(run.id)[0].id == task.id
    assert any(item["kind"] == "input" for item in store.list_artifacts(run.id))
