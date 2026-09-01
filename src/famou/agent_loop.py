"""Hermes-inspired continuous tool loop layered on a model Runtime.

This is an execution primitive, not a WebAgent stage machine. The durable controller owns
scheduling and recovery; this runtime owns one conversational session, local tools, and memory.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from .memory import MemoryStore
from .runtime import ModelTurn, OpenAICompatibleRuntime, RuntimeExecutionError, RuntimeResult
from .tools import LocalToolRegistry

HERMES_SYSTEM_PROMPT = """You are Lunar-Agent, a local-first general-purpose assistant inspired by
Hermes-style long-running sessions. Continue from the supplied goal and any relevant durable memory.
Use tools to inspect and change files, run explicitly permitted commands, and record useful facts in
memory. Work only inside the supplied task workspace. Be honest about what you actually did. Keep
the user informed with a concise final summary, including files changed and checks performed. When
memory tools are available, recall relevant notes before continuing old work and remember only
concise, reusable facts or decisions.
"""

# Compatibility alias for callers that imported the earlier experimental name.
BUILD_SYSTEM_PROMPT = HERMES_SYSTEM_PROMPT


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
        self._event_sink: Callable[[str, dict[str, object]], None] | None = None
        self._run_id: str | None = None
        self._task_id: str | None = None

    def set_context(self, run_id: str, task_id: str, goal: str | None = None) -> None:
        """Attach durable identity for memory scoping and observability."""
        del goal
        self._run_id = run_id
        self._task_id = task_id
        self.tools.set_memory_scope(f"run:{run_id}")

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
        messages: list[dict[str, object]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        # Memory is exposed through explicit model tool calls. We do not inject local notes into a
        # request implicitly: sending durable user context to a configured endpoint must remain an
        # intentional, per-run choice.
        messages.append({"role": "user", "content": prompt})
        artifacts: list[str] = []
        started = time.monotonic()
        model_turns = 0
        tool_steps = 0
        while True:
            remaining = self._remaining_timeout(started, timeout)
            turn = self.model.complete(messages, self.tools.schemas(), remaining)
            model_turns += 1
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
                return RuntimeResult(
                    text=turn.text,
                    artifacts=tuple(dict.fromkeys(artifacts)),
                    metadata={"provider": "openai-compatible", "mode": "agent-loop", "turns": str(model_turns)},
                )
            if tool_steps + len(turn.tool_calls) > self.max_steps:
                self._emit(
                    "agent_step_limit_reached",
                    {"max_steps": self.max_steps, "tool_steps": tool_steps},
                )
                raise RuntimeExecutionError(f"agent loop exceeded max steps ({self.max_steps})")
            messages.append(self._assistant_message(turn))
            for call in turn.tool_calls:
                result = self.tools.execute(call.name, call.arguments, workspace)
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
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result.output,
                    }
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


class HermesSessionRuntime(AgentLoopRuntime):
    """Named product-facing variant of :class:`AgentLoopRuntime`.

    The implementation is repository-owned; the name communicates the intended interaction model
    without implying that the user's Hermes package or configuration is imported.
    """

    name = "hermes-session"
