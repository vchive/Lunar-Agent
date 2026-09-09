"""Small staged subject orchestration seam.

This module owns stage scheduling and checkpoint evidence only.  It never creates a subject
receipt, invokes a harness, or turns a candidate into a score.  The normal effect-trial path can
use this seam inside its subject adapter without changing its outer receipt gate.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .agent_loop import AgentLoopRuntime
from .model_profile import UsageLedger
from .workflow_checkpoint import AggregateUsage, WorkflowCheckpointError, WorkflowController


@dataclass(frozen=True)
class StagedRunResult:
    status: str
    checkpoint_number: int | None
    resumed: bool
    error: str | None


class StagedWorkflowRunner:
    """Run master/build and an explicit, at-most-once continuation for one attempt."""

    def __init__(
        self,
        controller: WorkflowController,
        agent: AgentLoopRuntime,
        workspace: str | Path,
        *,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.controller = controller
        self.agent = agent
        self.workspace = Path(workspace).expanduser().absolute()
        self.usage_ledger = usage_ledger
        self._started = time.monotonic()
        self._resumed = False

    def run(
        self,
        *,
        master_prompt: str,
        plan: Sequence[str],
        expected_paths: Sequence[str],
        build_prompt: str,
        declared_paths: Sequence[str] = (),
        transcript: str | Path | None = None,
        timeout: float | None = None,
    ) -> StagedRunResult:
        """Execute master and build once; leave a checkpoint for an explicit resume."""
        try:
            self._set_transcript(transcript)
            self.agent.run(master_prompt, self.workspace, timeout=timeout, usage_ledger=self.usage_ledger)
            self.controller.write_master(plan, expected_paths)
            self.controller.transition("build_running")
            self._invoke_build(build_prompt, timeout)
            checkpoint = self._checkpoint("build_ready", declared_paths, transcript)
            return StagedRunResult("build_ready", checkpoint.number, False, None)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            checkpoint = self._checkpoint_safely("checkpointed", declared_paths, transcript)
            return StagedRunResult(
                "checkpointed" if checkpoint is not None else "failed",
                checkpoint.number if checkpoint is not None else None,
                False,
                type(exc).__name__,
            )

    def resume(
        self,
        *,
        prompt: str,
        declared_paths: Sequence[str] = (),
        transcript: str | Path | None = None,
        timeout: float | None = None,
    ) -> StagedRunResult:
        """Consume the one-resume guard, continue build, and checkpoint final readiness."""
        if self._resumed:
            raise WorkflowCheckpointError("staged runner resume is allowed only once")
        checkpoint = self.controller.resume()
        self._resumed = True
        self.controller.transition("build_running")
        try:
            self._set_transcript(transcript)
            self._invoke_build(prompt, timeout)
            final = self._checkpoint("build_ready", declared_paths, transcript)
            return StagedRunResult("build_ready", final.number, True, None)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            saved = self._checkpoint_safely("checkpointed", declared_paths, transcript)
            return StagedRunResult(
                "checkpointed" if saved is not None else "failed",
                saved.number if saved is not None else checkpoint.number,
                True,
                type(exc).__name__,
            )

    def _invoke_build(self, prompt: str, timeout: float | None) -> None:
        offset = self.agent.last_tool_steps
        self.agent.run(
            prompt,
            self.workspace,
            timeout=self._remaining(timeout),
            usage_ledger=self.usage_ledger,
            tool_steps_offset=offset,
        )

    def _set_transcript(self, transcript: str | Path | None) -> None:
        if transcript is not None and hasattr(self.agent, "set_session_path"):
            self.agent.set_session_path(transcript)

    def _remaining(self, timeout: float | None) -> float | None:
        if timeout is None:
            return None
        remaining = timeout - (time.monotonic() - self._started)
        if remaining <= 0:
            raise WorkflowCheckpointError("staged aggregate wall-time ceiling exceeded")
        return remaining

    def _usage(self) -> AggregateUsage:
        elapsed_ms = max(0, int((time.monotonic() - self._started) * 1000))
        steps = self.agent.last_tool_steps
        ledger = self.usage_ledger
        if ledger is None or ledger.snapshot.rounds == 0:
            return AggregateUsage.unavailable(rounds=0, tool_steps=steps, elapsed_ms=elapsed_ms)
        snapshot = ledger.snapshot
        return AggregateUsage(
            True,
            snapshot.input_tokens,
            snapshot.output_tokens,
            snapshot.total_tokens,
            snapshot.cost_micros,
            snapshot.rounds,
            steps,
            elapsed_ms,
        )

    def _checkpoint(
        self, stage: str, declared_paths: Sequence[str], transcript: str | Path | None
    ):
        return self.controller.checkpoint(
            stage=stage,
            declared_paths=declared_paths,
            usage=self._usage(),
            transcript=transcript,
        )

    def _checkpoint_safely(
        self, stage: str, declared_paths: Sequence[str], transcript: str | Path | None
    ):
        try:
            return self._checkpoint(stage, declared_paths, transcript)
        except (OSError, WorkflowCheckpointError):
            return None


__all__ = ["StagedRunResult", "StagedWorkflowRunner"]
