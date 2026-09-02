"""Bridge explicit Agent workers into the runtime-neutral evolution generator seam."""

from __future__ import annotations

import json
from collections.abc import Sequence

from .agents import AgentAdapter, AgentError, AgentRegistry, AgentRequest, AgentResult
from .algorithm import AlgorithmProblemContract
from .evolution import CandidateDraft, EvolutionError, GenerationRequest

MAX_GENERATION_PROMPT_BYTES = 60 * 1024
MAX_CONTEXT_ITEMS = 8


class AgentCandidateGenerator:
    """Use one explicitly selected Agent as a candidate source generator.

    The adapter is deliberately kept outside the evolution strategies.  A strategy sees only the
    existing ``CandidateGenerator`` callable, so deterministic callbacks and command generators
    remain valid and the evaluator boundary is unchanged.
    """

    def __init__(
        self,
        adapter: AgentAdapter,
        *,
        contract: AlgorithmProblemContract | None = None,
        role: str = "solver",
        required_capabilities: Sequence[str] = (),
        timeout: float | None = None,
    ) -> None:
        self.adapter = AgentRegistry([adapter]).select(role, tuple(required_capabilities))
        self.contract = contract
        self.role = role
        self.required_capabilities = tuple(required_capabilities)
        self.timeout = timeout
        self._calls = 0

    def __call__(self, request: GenerationRequest) -> CandidateDraft:
        self._calls += 1
        generation_workspace = (
            request.workspace
            / "evolution"
            / "agent"
            / "generations"
            / f"{request.iteration:08d}-{self._calls:04d}"
        ).resolve(strict=False)
        generation_workspace.mkdir(parents=True, exist_ok=True)
        prompt = self._prompt(request)
        agent_request = AgentRequest(
            run_id=f"evolution-{request.workspace.name or 'workspace'}",
            task_id=f"generation-{request.iteration:08d}-{self._calls:04d}",
            role=self.role,
            prompt=prompt,
            required_capabilities=self.required_capabilities,
            workspace=generation_workspace,
            timeout=self.timeout,
        )
        try:
            result = self.adapter.run(agent_request)
        except AgentError as exc:
            raise EvolutionError(f"agent candidate generation failed: {_bounded_error(exc)}") from exc
        except Exception as exc:
            raise EvolutionError(f"agent candidate generation failed: {_bounded_error(exc)}") from exc
        if not isinstance(result, AgentResult):
            raise EvolutionError("agent candidate generation returned an invalid result")
        if result.status != "succeeded":
            raise EvolutionError(
                f"agent candidate generation returned {result.status}: "
                f"{_bounded_error(result.error or 'no error detail')}"
            )
        return self._draft(result.text)

    def _prompt(self, request: GenerationRequest) -> str:
        contract = request.workspace / "evolution" / "contract.json"
        contract_summary: object = (
            self.contract.to_dict() if self.contract is not None else {"workspace_contract": str(contract)}
        )
        # The canonical contract is already persisted by LocalController. Reading it here keeps
        # the Agent prompt aligned with resume state without copying large source artifacts.
        try:
            payload = json.loads(contract.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                contract_summary = {
                    key: payload.get(key)
                    for key in (
                        "problem_id",
                        "problem_type",
                        "statement",
                        "objective",
                        "decision_variables",
                        "prediction_target",
                        "success_criteria",
                        "deliverables",
                    )
                    if key in payload
                }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # Standalone callers may not persist a canonical contract; the in-memory summary below
            # still gives the Agent enough bounded context to propose a candidate.
            if self.contract is None:
                contract_summary = {
                    "problem_type": request.workspace.name,
                    "statement": "Read the algorithm contract and propose a candidate implementation.",
                }
        context = {
            "iteration": request.iteration,
            "contract": contract_summary,
            "parent": _candidate_summary(request.parent),
            "inspirations": [_candidate_summary(item) for item in request.inspirations[:MAX_CONTEXT_ITEMS]],
            "archive": [_candidate_summary(item) for item in request.archive[-MAX_CONTEXT_ITEMS:]],
            "workspace": str(request.workspace),
        }
        encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2)
        prompt = (
            "You are the solver in a bounded local algorithm-evolution run.\n"
            "Read any needed inputs from the supplied workspace. Propose one executable candidate "
            "that improves the objective and respects hard constraints. Return either plain source "
            "text or a JSON object with source, optional filename, and scalar metadata. Do not "
            "return a success claim, evaluation report, or markdown explanation.\n\n"
            "Generation context:\n"
            f"{encoded}"
        )
        if len(prompt.encode("utf-8")) > MAX_GENERATION_PROMPT_BYTES:
            raise EvolutionError("agent generation prompt exceeds the bounded size")
        return prompt

    def _draft(self, text: str) -> CandidateDraft:
        stripped = text.strip()
        if not stripped:
            raise EvolutionError("agent returned empty candidate source")
        if stripped[:1] in {"{", "["}:
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise EvolutionError("agent candidate response contains malformed JSON") from exc
            if not isinstance(payload, dict) or "source" not in payload:
                raise EvolutionError("agent candidate JSON must contain source")
            try:
                metadata = payload.get("metadata", {})
                if not isinstance(metadata, dict):
                    raise EvolutionError("agent candidate metadata must be an object")
                metadata = {**metadata, "agent_adapter": self.adapter.name}
                return CandidateDraft(
                    payload["source"],
                    payload.get("filename", "candidate.py"),
                    metadata,
                )
            except (TypeError, ValueError, EvolutionError) as exc:
                raise EvolutionError(f"agent candidate is invalid: {_bounded_error(exc)}") from exc
        try:
            return CandidateDraft(stripped, metadata={"agent_adapter": self.adapter.name})
        except (TypeError, ValueError, EvolutionError) as exc:
            raise EvolutionError(f"agent candidate is invalid: {_bounded_error(exc)}") from exc


def _candidate_summary(candidate: object) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "candidate_id": getattr(candidate, "candidate_id", None),
        "code_path": getattr(candidate, "code_path", None),
        "parent_id": getattr(candidate, "parent_id", None),
        "iteration": getattr(candidate, "iteration", None),
        "generation": getattr(candidate, "generation", None),
        "island_id": getattr(candidate, "island_id", None),
        "validity": getattr(getattr(candidate, "evaluation", None), "validity", None),
        "combined_score": getattr(getattr(candidate, "evaluation", None), "combined_score", None),
    }


def _bounded_error(error: object) -> str:
    text = " ".join(str(error).split()).strip()
    return text[-2_000:] if text else "unknown agent generation error"


__all__ = ["AgentCandidateGenerator"]
