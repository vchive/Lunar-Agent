"""Hermes-inspired continuous tool loop layered on a model Runtime.

This is an execution primitive, not a WebAgent stage machine. The durable controller owns
scheduling and recovery; this runtime owns one conversational session, local tools, and memory.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from .memory import MemoryStore
from .runtime import ModelTurn, OpenAICompatibleRuntime, RuntimeExecutionError, RuntimeResult
from .tools import LocalToolRegistry
from .transcript import SessionTranscript

HERMES_SYSTEM_PROMPT = """You are Lunar-Agent, a local-first general-purpose assistant inspired by
Hermes-style long-running sessions. Continue from the supplied goal and any relevant durable memory.
Use tools to inspect and change files, run explicitly permitted commands, and record useful facts in
memory. Work only inside the supplied task workspace. Be honest about what you actually did. Keep
the user informed with a concise final summary, including files changed and checks performed. When
memory tools are available, recall relevant notes before continuing old work and remember only
concise, reusable facts or decisions.
"""
ISOLATED_SYSTEM_PROMPT = """You are executing one stateless Lunar-Agent protocol step. Follow the
user message exactly, return only its requested machine-readable response, and do not use tools,
memory, session history, or unstated external context.
"""

# Compatibility alias for callers that imported the earlier experimental name.
BUILD_SYSTEM_PROMPT = HERMES_SYSTEM_PROMPT
_SECRET_TEXT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


def _bounded_runtime_error(error: object, limit: int = 512) -> str:
    text = _SECRET_TEXT.sub("[REDACTED]", " ".join(str(error).split()))
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = "\n[truncated]"
    budget = max(1, limit - len(suffix.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


class AgentInputRequired(RuntimeExecutionError):
    """Raised when a session intentionally pauses for a user/parent-Agent answer."""

    def __init__(self, question: str, options: tuple[str, ...] = ()) -> None:
        super().__init__(question)
        self.question = question
        self.options = options


class AgentLoopRuntime:
    """Execute one bounded Hermes-style session with optional persistent memory."""

    name = "agent-loop"

    def __init__(
        self,
        model: OpenAICompatibleRuntime,
        tools: LocalToolRegistry | None = None,
        max_steps: int = 40,
        system_prompt: str = HERMES_SYSTEM_PROMPT,
        memory: MemoryStore | None = None,
        session_history: bool = False,
        transcript: SessionTranscript | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model = model
        self.memory = memory
        self.tools = tools or LocalToolRegistry(memory=memory)
        if memory is not None and self.tools.memory is None:
            self.tools.memory = memory
        api_key = getattr(model, "api_key", None)
        if isinstance(api_key, str) and api_key and api_key not in self.tools.redactions:
            self.tools.redactions = (*self.tools.redactions, api_key)
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.session_history = session_history or transcript is not None
        self._transcript = transcript
        self._event_sink: Callable[[str, dict[str, object]], None] | None = None
        self._run_id: str | None = None
        self._task_id: str | None = None

    def set_context(self, run_id: str, task_id: str, goal: str | None = None) -> None:
        """Attach durable identity for memory scoping and observability."""
        del goal
        self._run_id = run_id
        self._task_id = task_id
        self.tools.set_memory_scope(f"run:{run_id}")

    def set_session_path(self, path: str | Path) -> None:
        """Attach a stable run/task transcript path when session history is enabled."""
        if not self.session_history:
            return
        api_key = getattr(self.model, "api_key", None)
        redactions = (api_key,) if isinstance(api_key, str) and api_key else ()
        self._transcript = SessionTranscript(path, redactions=redactions)

    def session_path(self) -> Path | None:
        return self._transcript.path if self._transcript is not None else None

    def set_event_sink(self, sink: Callable[[str, dict[str, object]], None] | None) -> None:
        self._event_sink = sink

    def set_process_observer(self, observer: Callable[[int, int | None], None] | None) -> None:
        self.model.set_process_observer(observer)

    def process_info(self) -> tuple[int | None, int | None]:
        return self.model.process_info()

    def cancel(self) -> None:
        self.model.cancel()

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        workspace.mkdir(parents=True, exist_ok=True)
        messages = self._initial_messages(prompt)
        # Memory is exposed through explicit model tool calls. We do not inject local notes into a
        # request implicitly: sending durable user context to a configured endpoint must remain an
        # intentional, per-run choice.
        artifacts: list[str] = []
        started = time.monotonic()
        model_turns = 0
        tool_steps = 0
        response_models: list[str | None] = []
        usages: list[dict[str, int] | None] = []
        while True:
            remaining = self._remaining_timeout(started, timeout)
            try:
                turn = self.model.complete(messages, self.tools.schemas(), remaining)
            except AgentInputRequired:
                raise
            except Exception as exc:
                self._emit(
                    "agent_runtime_failure",
                    {"phase": "model_turn", "error": _bounded_runtime_error(exc)},
                )
                raise
            model_turns += 1
            response_models.append(turn.response_model)
            usages.append(turn.usage)
            self._emit(
                "agent_model_turn",
                {
                    "turn": model_turns,
                    "tool_call_count": len(turn.tool_calls),
                    "has_text": bool(turn.text),
                    "tool_steps": tool_steps,
                },
            )
            if not turn.tool_calls:
                if not turn.text:
                    raise RuntimeExecutionError("agent loop ended without a final text result")
                final_message = {"role": "assistant", "content": turn.text}
                self._append_transcript(final_message)
                metadata = {
                    "provider": "openai-compatible",
                    "mode": "agent-loop",
                    "turns": str(model_turns),
                    "session_history": str(self.session_history).lower(),
                }
                if response_models and all(response_models) and len(set(response_models)) == 1:
                    metadata["response_model"] = str(response_models[0])
                if usages and all(value is not None for value in usages):
                    for key in ("input_tokens", "output_tokens", "total_tokens"):
                        metadata[key] = str(sum(value[key] for value in usages if value is not None))
                return RuntimeResult(
                    text=turn.text,
                    artifacts=tuple(dict.fromkeys(artifacts)),
                    metadata=metadata,
                )
            if tool_steps + len(turn.tool_calls) > self.max_steps:
                self._emit(
                    "agent_step_limit_reached",
                    {"max_steps": self.max_steps, "tool_steps": tool_steps},
                )
                raise RuntimeExecutionError(f"agent loop exceeded max steps ({self.max_steps})")
            messages.append(self._assistant_message(turn))
            self._append_transcript(messages[-1])
            for call in turn.tool_calls:
                try:
                    result = self.tools.execute(call.name, call.arguments, workspace)
                except Exception as exc:
                    self._emit(
                        "agent_runtime_failure",
                        {"phase": "tool", "tool": call.name, "error": _bounded_runtime_error(exc)},
                    )
                    raise
                tool_steps += 1
                artifacts.extend(result.artifacts)
                self._emit(
                    "agent_tool_result",
                    {
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "success": result.success,
                        "artifact_count": len(result.artifacts),
                        "output_bytes": len(result.output.encode("utf-8")),
                        "awaiting_input": result.awaiting_input,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result.output,
                    }
                )
                self._append_transcript(messages[-1])
                if result.awaiting_input:
                    raise AgentInputRequired(
                        result.input_question or result.output[:8_000], result.input_options
                    )

    def run_isolated(
        self, prompt: str, workspace: Path, timeout: float | None = None
    ) -> RuntimeResult:
        """Run one stateless, tool-free model turn for a trust-boundary decision.

        Evaluator compilation and adversarial audit must not inherit the user's durable transcript,
        memory tools, or a previous compiler response. Keeping this primitive on the repository-
        owned loop lets protocol code request that boundary without depending on model internals.
        """
        workspace.mkdir(parents=True, exist_ok=True)
        turn = self.model.complete(
            [
                {"role": "system", "content": ISOLATED_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            (),
            timeout,
        )
        if turn.tool_calls:
            raise RuntimeExecutionError("isolated agent turn returned tool calls")
        if not turn.text:
            raise RuntimeExecutionError("isolated agent turn returned empty content")
        return RuntimeResult(
            text=turn.text,
            metadata={
                "provider": "openai-compatible",
                "mode": "agent-loop-isolated",
                "session_history": "false",
            },
        )

    @staticmethod
    def _remaining_timeout(started: float, timeout: float | None) -> float | None:
        if timeout is None:
            return None
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeExecutionError("agent loop timed out before the next model turn")
        return remaining

    @staticmethod
    def _assistant_message(turn: ModelTurn) -> dict[str, object]:
        tool_calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in turn.tool_calls
        ]
        return {"role": "assistant", "content": turn.text or None, "tool_calls": tool_calls}

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, payload)

    def _initial_messages(self, prompt: str) -> list[dict[str, object]]:
        if not self.session_history or self._transcript is None:
            return [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ]
        loaded = self._transcript.load()
        messages = list(loaded)
        has_system = any(message.get("role") == "system" for message in messages)
        if not has_system:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
            if not loaded:
                self._append_transcript(messages[0])
        appended_prompt = not messages or messages[-1].get("content") != prompt or messages[-1].get("role") != "user"
        if appended_prompt:
            messages.append({"role": "user", "content": prompt})
        # Persist only the newly appended continuation prompt; the loader already returned the
        # previous bounded messages and writing them again would duplicate the transcript.
        if appended_prompt:
            self._append_transcript(messages[-1])
        return messages

    def _append_transcript(self, message: dict[str, object]) -> None:
        if self.session_history and self._transcript is not None:
            self._transcript.append(message)


class HermesSessionRuntime(AgentLoopRuntime):
    """Named product-facing variant of :class:`AgentLoopRuntime`.

    The implementation is repository-owned; the name communicates the intended interaction model
    without implying that the user's Hermes package or configuration is imported.
    """

    name = "hermes-session"
