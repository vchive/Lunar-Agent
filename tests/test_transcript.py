import json
from pathlib import Path

from famou.agent_loop import AgentLoopRuntime
from famou.runtime import ModelTurn, ToolCall
from famou.tools import LocalToolRegistry
from famou.transcript import SessionTranscript


class TranscriptModel:
    name = "transcript-fixture"

    def __init__(self, turns: list[ModelTurn], api_key: str | None = None) -> None:
        self.turns = list(turns)
        self.api_key = api_key
        self.requests: list[list[dict[str, object]]] = []

    def complete(self, messages, tools=(), timeout=None):
        del tools, timeout
        self.requests.append(messages)
        return self.turns.pop(0)

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_transcript_is_bounded_and_redacts_secret(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        tmp_path / "session.jsonl",
        max_messages=3,
        max_message_bytes=256,
        max_total_bytes=700,
        redactions=("secret-key",),
    )
    for index in range(5):
        transcript.append({"role": "user", "content": f"secret-key {index} " + "x" * 300})

    raw = transcript.path.read_bytes()
    assert len(raw) <= 700
    loaded = transcript.load()
    assert len(loaded) <= 3
    assert "secret-key" not in transcript.path.read_text()


def test_session_history_replays_recent_messages_without_duplicate_system(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    first_model = TranscriptModel(
        [
            ModelTurn("", (ToolCall("1", "write_file", {"path": "x.txt", "content": "x"}),)),
            ModelTurn("saved", ()),
        ],
        api_key="secret-key",
    )
    first = AgentLoopRuntime(
        first_model,
        tools=LocalToolRegistry(redactions=("secret-key",)),
        session_history=True,
    )
    first.set_session_path(path)
    first.run("save a file using secret-key", tmp_path / "workspace")

    second_model = TranscriptModel([ModelTurn("continued", ())], api_key="secret-key")
    second = AgentLoopRuntime(
        second_model,
        tools=LocalToolRegistry(redactions=("secret-key",)),
        session_history=True,
    )
    second.set_session_path(path)
    second.run("continue", tmp_path / "workspace")

    messages = second_model.requests[0]
    assert sum(message.get("role") == "system" for message in messages) == 1
    assert any(message.get("content") == "saved" for message in messages)
    assert "secret-key" not in path.read_text()
    assert all(json.dumps(message) for message in messages)
