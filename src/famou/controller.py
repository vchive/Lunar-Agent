"""Durable local scheduler for Hermes-inspired agent sessions."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .agent_loop import AgentInputRequired
from .agents import (
    AgentAdapter,
    AgentInvocationError,
    AgentRegistry,
    AgentRequest,
    AgentResult,
    AgentSelectionError,
    RuntimeAgentAdapter,
)
from .algorithm import (
    MAX_INPUT_FILE_BYTES,
    MAX_INPUT_FILES,
    AlgorithmProblemContract,
    OutputSpec,
    materialize_algorithm_workspace,
)
from .artifacts import ArtifactError, ArtifactStore
from .budget import BudgetExceeded, BudgetSpec
from .config import Config
from .conversational import (
    CompilationResult,
    ContractCompilationError,
    ContractCompiler,
    build_algorithm_plan,
)
from .evaluator import MAX_ARTIFACT_BYTES, Evaluation, Evaluator, acceptance_evaluator
from .evolution import (
    CandidateEvaluator,
    CandidateExecution,
    CandidateGenerator,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    StrategyResult,
    build_strategy,
)
from .memory import MemoryStore
from .models import Run, RunStatus
from .policy import MasterPolicy, PlanDocument, PlanPatch, PolicyDecision
from .profiles import ProfileRegistry
from .recovery import RecoveryPolicy, RecoveryProposal
from .routing import DomainRouter, RouteDecision
from .runtime import Runtime, RuntimeExecutionError
from .store import Store


class LocalController:
    _RETRY_FEEDBACK_RULES = frozenset(
        {
            "result_contains",
            "artifact_exists",
            "artifact_text_contains",
            "json_parse",
            "json_has_keys",
            "output_valid",
            "artifact_valid",
            "data_profile_valid",
            "evaluation_report_valid",
            "all",
            "any",
        }
    )
    _MAX_RETRY_FEEDBACK_VALUES = 16
    _MAX_RETRY_FEEDBACK_BYTES = 8_000

    def __init__(
        self,
        config: Config,
        runtime: Runtime,
        evaluator: Evaluator | None = None,
        store: Store | None = None,
        memory: MemoryStore | None = None,
        router: DomainRouter | None = None,
        profiles: ProfileRegistry | None = None,
        runtime_factory: Callable[[], Runtime] | None = None,
        agent_registry: AgentRegistry | None = None,
        max_workers: int = 1,
    ) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if max_workers > 1 and runtime_factory is None:
            raise ValueError("runtime_factory is required when max_workers is greater than 1")
        self.config = config
        self.config.ensure()
        self.store = store or Store(config.database)
        self.store.initialize()
        self.memory = memory or MemoryStore(config.database)
        self.memory.initialize()
        self.runtime = runtime
        self.runtime_factory = runtime_factory
        self.max_workers = max_workers
        self._active_lock = threading.Lock()
        self._active_runtimes: dict[str, Runtime] = {}
        self._active_agents: dict[str, AgentAdapter] = {}
        self.evaluator = evaluator
        self.router = router or DomainRouter()
        self.profiles = profiles or ProfileRegistry()
        self.policy = MasterPolicy()
        self.recovery_policy = RecoveryPolicy()
        self.agent_registry = agent_registry or AgentRegistry([RuntimeAgentAdapter(runtime)])

    def _register_algorithm_workspace(self, run: Run, document: PlanDocument) -> None:
        """Materialize the fixed role workspace for a validated algorithm contract."""
        if document.algorithm_problem is None:
            return
        contract = AlgorithmProblemContract.from_dict(document.algorithm_problem)
        manifest = materialize_algorithm_workspace(run.workspace, contract, document.plan_id, document.version)
        tasks = self.store.list_tasks(run.id)
        if tasks:
            ArtifactStore(run.workspace, self.store, run.id).record(
                manifest, tasks[0].id, kind="algorithm_manifest"
            )
        self.store.append_event(
            run.id,
            "algorithm_contract_registered",
            {
                "problem_id": contract.problem_id,
                "plan_id": document.plan_id,
                "plan_version": document.version,
                "contract_sha256": contract.digest(),
                "evolution_strategy": contract.evolution.strategy,
            },
            event_id=f"event-algorithm-contract-{document.plan_id}-{document.version}",
        )

    def decide(self, goal: str) -> PolicyDecision:
        """Return a bounded deterministic Master decision without creating durable work."""
        return self.policy.decide(goal)

    def create_evolution_run(
        self,
        contract: AlgorithmProblemContract,
        *,
        workspace: str | Path | None = None,
    ) -> Run:
        """Create a ledger-backed run for a local evolution strategy.

        Candidate generation/evaluation is intentionally supplied later by ``run_evolution`` so
        creating a detached handle never needs to instantiate an agent runtime.  The validated
        contract is copied into the run workspace and becomes the immutable local source of truth.
        """
        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        run = self.store.create_run(
            f"Evolve algorithm problem {contract.problem_id}",
            workspace=workspace,
            tasks=[
                {
                    "id": "evolution",
                    "title": f"Evolve {contract.problem_id}",
                    "prompt": contract.statement,
                    "acceptance": None,
                }
            ],
        )
        evolution_root = Path(run.workspace) / "evolution"
        if evolution_root.exists() and evolution_root.is_symlink():
            raise EvolutionError("evolution directory must not be a symlink")
        evolution_root.mkdir(parents=True, exist_ok=True)
        contract_path = evolution_root / "contract.json"
        if contract_path.exists() and contract_path.is_symlink():
            raise EvolutionError("evolution contract must not be a symlink")
        contract_path.write_text(
            json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        task = self.store.list_tasks(run.id)[0]
        ArtifactStore(run.workspace, self.store, run.id).record(
            contract_path, task.id, kind="evolution_contract"
        )
        self.store.append_event(
            run.id,
            "evolution_configured",
            {
                "problem_id": contract.problem_id,
                "contract_sha256": contract.digest(),
                "strategy": contract.evolution.strategy,
                "workspace": "evolution",
            },
            task_id=task.id,
        )
        return run

    def copy_staged_inputs(self, source_run_id: str, target_run_id: str) -> tuple[str, ...]:
        """Copy verified run inputs into another local run without carrying source paths.

        The target must already have a task (evolution runs do); copied rows use the existing
        ``input_data`` artifact kind and retain the source bytes' digest/size. Repeating the
        operation with identical bytes is idempotent, while a conflicting target file fails
        before any strategy can consume it.
        """
        source_run = self.store.get_run(source_run_id)
        target_run = self.store.get_run(target_run_id)
        if source_run is None or target_run is None:
            raise ValueError("source and target runs must exist")
        target_tasks = self.store.list_tasks(target_run.id)
        if not target_tasks:
            raise EvolutionError("target run has no task to own copied inputs")
        source_root = Path(source_run.workspace).expanduser().resolve(strict=False)
        target_root = Path(target_run.workspace).expanduser().resolve(strict=False)
        target_task = target_tasks[0]
        artifact_store = ArtifactStore(target_root, self.store, target_run.id)
        copied: list[str] = []
        for item in self.store.list_artifacts(source_run.id):
            if item.get("kind") != "input_data":
                continue
            relative = item.get("path")
            expected_digest = item.get("sha256")
            expected_size = item.get("size")
            if (
                not isinstance(relative, str)
                or not relative.startswith("data/raw/")
                or not isinstance(expected_digest, str)
                or not isinstance(expected_size, int)
                or expected_size < 0
                or expected_size > MAX_INPUT_FILE_BYTES
            ):
                raise ArtifactError("source input artifact metadata is malformed")
            source = self._confined_regular_file(source_root, relative)
            if source is None:
                raise ArtifactError(f"source input is missing or unsafe: {relative}")
            content = source.read_bytes()
            if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
                raise ArtifactError(f"source input digest does not match the ledger: {relative}")
            target = target_root / relative
            if self._raw_path_has_symlink(target_root, target):
                raise ArtifactError(f"target input path is symlinked: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest:
                    raise ArtifactError(f"target input already contains different data: {relative}")
            else:
                temporary = target.with_name(f".{target.name}.tmp")
                temporary.write_bytes(content)
                temporary.replace(target)
            if not any(
                existing.get("path") == relative
                and existing.get("kind") == "input_data"
                and existing.get("sha256") == expected_digest
                for existing in self.store.list_artifacts(target_run.id)
            ):
                artifact_store.record(target, target_task.id, kind="input_data")
            self.store.append_event(
                target_run.id,
                "algorithm_input_copied",
                {"path": relative, "size": expected_size, "sha256": expected_digest},
                task_id=target_task.id,
                event_id=(
                    "event-algorithm-input-copy-"
                    + hashlib.sha256(f"{source_run.id}\0{relative}".encode()).hexdigest()
                ),
            )
            copied.append(relative)
        return tuple(copied)

    def run_evolution(
        self,
        run_id: str,
        contract: AlgorithmProblemContract,
        generator: CandidateGenerator,
        evaluator: CandidateEvaluator,
        evolution_config: EvolutionConfig,
        *,
        resume: bool = False,
    ) -> tuple[Run, StrategyResult]:
        """Execute or resume an evolution strategy while retaining SQLite run authority."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        contract_path = Path(run.workspace) / "evolution" / "contract.json"
        if not contract_path.is_file():
            raise EvolutionError("evolution run is missing its canonical contract")
        try:
            stored_contract = AlgorithmProblemContract.from_dict(
                json.loads(contract_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("canonical evolution contract is invalid") from exc
        if stored_contract.digest() != contract.digest():
            raise EvolutionError("supplied contract does not match the run contract")
        task = self.store.list_tasks(run.id)
        if len(task) != 1:
            raise EvolutionError("evolution run must contain exactly one task")
        evolution_task = task[0]

        context = EvolutionContext(
            contract=contract,
            workspace=Path(run.workspace),
            generate=generator,
            evaluate=evaluator,
            config=evolution_config,
            cancelled=lambda: (
                (latest := self.store.get_run(run_id)) is None
                or latest.status == RunStatus.CANCELLED
            ),
            observe=lambda event, payload: self._observe_evolution(run_id, evolution_task.id, event, payload),
        )
        strategy = build_strategy(context)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run, strategy.resume()
        if resume:
            self.store.recover_running(run.id)
        attempt = self.store.claim_task(evolution_task.id, f"evolution:{evolution_config.strategy}")
        if attempt is None:
            latest = self.store.get_run(run.id)
            if latest is not None and latest.status == RunStatus.CANCELLED:
                return latest, strategy.resume()
            raise EvolutionError("evolution task is already claimed or not runnable")
        self.store.append_event(
            run.id,
            "evolution_started",
            {
                "strategy": evolution_config.strategy,
                "resume": resume,
                "contract_sha256": contract.digest(),
            },
            task_id=evolution_task.id,
        )
        try:
            result = strategy.resume() if resume else strategy.run()
            result_path = Path(run.workspace) / "evolution" / "result.json"
            result_path.write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            artifacts = ArtifactStore(run.workspace, self.store, run.id)
            execution_root = Path(run.workspace) / "evolution" / "candidates"
            if execution_root.is_dir() and not execution_root.is_symlink():
                for execution_path in sorted(execution_root.glob("*/execution.json")):
                    if execution_path.is_symlink() or not execution_path.is_file():
                        continue
                    relative = execution_path.resolve(strict=False).relative_to(
                        Path(run.workspace).resolve()
                    )
                    if not any(
                        item["path"] == relative.as_posix()
                        and item["kind"] == "candidate_execution"
                        for item in self.store.list_artifacts(run.id)
                    ):
                        artifacts.record(
                            execution_path,
                            evolution_task.id,
                            kind="candidate_execution",
                        )
                    try:
                        execution = CandidateExecution.from_dict(
                            json.loads(execution_path.read_text(encoding="utf-8"))
                        )
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                        continue
                    for declared in execution.artifacts:
                        declared_path = execution_path.parent / declared
                        if declared_path.is_symlink() or not declared_path.is_file():
                            continue
                        try:
                            declared_path.resolve(strict=False).relative_to(
                                Path(run.workspace).resolve()
                            )
                        except ValueError:
                            continue
                        relative_declared = declared_path.resolve(strict=False).relative_to(
                            Path(run.workspace).resolve()
                        )
                        if not any(
                            item["path"] == relative_declared.as_posix()
                            and item["kind"] == "candidate_execution_output"
                            for item in self.store.list_artifacts(run.id)
                        ):
                            artifacts.record(
                                declared_path,
                                evolution_task.id,
                                kind="candidate_execution_output",
                            )
            for relative, kind in (
                ("evolution/archive.jsonl", "evolution_archive"),
                ("evolution/state.json", "evolution_state"),
                ("evolution/result.json", "result"),
            ):
                path = Path(run.workspace) / relative
                if path.is_file() and not any(
                    item["path"] == relative and item["kind"] == kind
                    for item in self.store.list_artifacts(run.id)
                ):
                    artifacts.record(path, evolution_task.id, kind=kind)
            self.store.append_event(
                run.id,
                "evolution_finished",
                result.to_dict(),
                task_id=evolution_task.id,
            )
            if result.status == "failed":
                self.store.append_event(
                    run.id,
                    "evolution_failed",
                    result.to_dict(),
                    task_id=evolution_task.id,
                )
            success = result.status in {"completed", "stagnated"} and result.best_candidate_id is not None
            if result.status == "cancelled":
                # A concurrent ``cancel`` already settled the task; do not overwrite it.
                self.store.append_event(run.id, "evolution_cancelled", result.to_dict(), task_id=evolution_task.id)
            else:
                self.store.finish_task(
                    evolution_task.id,
                    attempt.id,
                    success,
                    result_path="evolution/result.json",
                    error=result.error if not success else None,
                )
            settled = self.store.settle_run(run.id)
            return settled or run, result
        except Exception as exc:
            error = " ".join(str(exc).split())[-2_000:] or "evolution failed"
            self.store.append_event(
                run.id,
                "evolution_failed",
                {"error": error, "strategy": evolution_config.strategy},
                task_id=evolution_task.id,
            )
            self.store.finish_task(
                evolution_task.id,
                attempt.id,
                False,
                result_path=None,
                error=error,
            )
            settled = self.store.settle_run(run.id)
            raise EvolutionError(error) from exc

    def _observe_evolution(
        self, run_id: str, task_id: str, event: str, payload: dict[str, object]
    ) -> None:
        if event == "candidate":
            self.store.append_event(run_id, "evolution_candidate_archived", payload, task_id=task_id)
        elif event == "state" and payload.get("status") == "running":
            self.store.append_event(run_id, "evolution_iteration", payload, task_id=task_id)
        elif event == "agent_artifact":
            self._record_evolution_agent_artifact(run_id, task_id, payload)
        elif event in {
            "agent_model_turn",
            "agent_tool_result",
            "agent_step_limit_reached",
            "agent_runtime_failure",
        }:
            # RuntimeAgentAdapter has already reduced this payload to bounded scalar metadata.
            # Keep the original event name so status/events consumers can distinguish model,
            # tool, and failure phases without inspecting a provider-specific trace.
            self.store.append_event(run_id, event, payload, task_id=task_id)

    def _record_evolution_agent_artifact(
        self, run_id: str, task_id: str, payload: dict[str, object]
    ) -> None:
        path_value = payload.get("path")
        kind = payload.get("kind")
        if not isinstance(path_value, str) or not isinstance(kind, str):
            raise EvolutionError("evolution Agent artifact evidence is malformed")
        if kind not in {"evolution_agent_transcript", "evolution_agent_artifact"}:
            raise EvolutionError("evolution Agent artifact kind is unsupported")
        run = self.store.get_run(run_id)
        if run is None:
            raise EvolutionError("evolution Agent artifact references an unknown run")
        root = Path(run.workspace).expanduser().resolve(strict=False)
        raw = root / path_value
        current = raw
        while True:
            if current.exists() and current.is_symlink():
                raise EvolutionError("evolution Agent artifact must not be a symlink")
            if current == root:
                break
            try:
                current.relative_to(root)
            except ValueError as exc:
                raise EvolutionError("evolution Agent artifact escapes the run workspace") from exc
            parent = current.parent
            if parent == current:
                raise EvolutionError("evolution Agent artifact escapes the run workspace")
            current = parent
        resolved = raw.resolve(strict=False)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvolutionError("evolution Agent artifact escapes the run workspace") from exc
        if relative != path_value or not resolved.is_file() or resolved.is_symlink():
            raise EvolutionError("evolution Agent artifact must be a regular run-relative file")
        if resolved.stat().st_size > 1 * 1024 * 1024:
            raise EvolutionError("evolution Agent artifact exceeds the bounded evidence size")
        artifacts = ArtifactStore(root, self.store, run_id)
        existing = next(
            (
                item
                for item in self.store.list_artifacts(run_id)
                if item["path"] == relative and item["kind"] == kind
            ),
            None,
        )
        artifact_id = existing["id"] if existing is not None else artifacts.record(
            resolved, task_id, kind=kind
        )
        event_id = "event-evolution-agent-artifact-" + hashlib.sha256(
            f"{relative}\0{kind}".encode()
        ).hexdigest()
        self.store.append_event(
            run_id,
            "evolution_agent_artifact",
            {
                "artifact_id": artifact_id,
                "path": relative,
                "kind": kind,
                "size": resolved.stat().st_size,
                "role": payload.get("role"),
                "adapter": payload.get("adapter"),
                "agent_task_id": payload.get("task_id"),
            },
            task_id=task_id,
            event_id=event_id,
        )

    def start_plan(self, document: PlanDocument, decision: PolicyDecision | None = None) -> Run:
        if decision is None:
            decision = PolicyDecision(
                "execute_plan",
                "A caller supplied a validated multi-step plan",
                1.0,
                plan_id=document.plan_id,
                plan_version=document.version,
                evidence=("explicit plan document",),
            )
        elif decision.action != "execute_plan":
            raise ValueError("a planned run requires an execute_plan decision")
        elif decision.plan_id is None:
            decision = PolicyDecision(
                decision.action,
                decision.rationale,
                decision.confidence,
                decision.questions,
                document.plan_id,
                document.version,
                decision.evidence,
                decision.plan,
            )
        elif (decision.plan_id, decision.plan_version) != (document.plan_id, document.version):
            raise ValueError("execute_plan decision does not reference the supplied plan revision")
        route = self.router.route(document.goal)
        if document.budget != BudgetSpec():
            route = RouteDecision(route.domain, route.reason, route.confidence, route.required_capabilities,
                                  route.solver_profile, route.evaluator_profile, document.budget, route.evidence)
        self._validate_route(route)
        run = self.store.create_run_with_plan(document, decision, route=route)
        self._register_algorithm_workspace(run, document)
        return self.resume(run.id)

    def patch_plan(self, run_id: str, patch: PlanPatch) -> PlanDocument:
        return self.store.patch_plan(run_id, patch)

    def replan(self, run_id: str, document: PlanDocument, reason: str, evidence: tuple[str, ...] = ()) -> PlanDocument:
        current = self.store.get_current_plan(run_id)
        if current is None:
            raise ValueError("run has no current plan")
        if document.plan_id != current.plan_id:
            raise ValueError("replan must retain the current plan id")
        inherited_budget = current.budget if document.budget == BudgetSpec() else document.budget
        if document.parent_version is None:
            document = PlanDocument(
                goal=document.goal, tasks=document.tasks, plan_id=document.plan_id,
                version=current.version + 1, parent_version=current.version,
                schema_version=document.schema_version, hard_constraints=document.hard_constraints,
                soft_constraints=document.soft_constraints, objective=document.objective,
                evidence=document.evidence, assumptions=document.assumptions,
                acceptance=document.acceptance, verification=document.verification, delivery=document.delivery,
                budget=inherited_budget, algorithm_problem=document.algorithm_problem,
            )
        elif inherited_budget != document.budget:
            document = PlanDocument(
                goal=document.goal, tasks=document.tasks, plan_id=document.plan_id,
                version=document.version, parent_version=document.parent_version,
                schema_version=document.schema_version, hard_constraints=document.hard_constraints,
                soft_constraints=document.soft_constraints, objective=document.objective,
                evidence=document.evidence, assumptions=document.assumptions,
                acceptance=document.acceptance, verification=document.verification, delivery=document.delivery,
                budget=inherited_budget, algorithm_problem=document.algorithm_problem,
            )
        committed = self.store.commit_plan_revision(run_id, document, reason, evidence, action="replan")
        run = self.store.get_run(run_id)
        if run is not None:
            self._register_algorithm_workspace(run, committed)
        return committed

    def deliver(self, run_id: str) -> PolicyDecision:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        tasks = self.store.list_tasks(run_id)
        artifacts = self.store.list_artifacts(run_id)
        evaluations = [event for event in self.store.list_events(run_id) if event["type"] == "task_evaluated"]
        passed = bool(tasks) and run.status == RunStatus.SUCCEEDED and all(
            any(item.get("task_id") == task.id and item["payload"].get("passed") is True for item in evaluations)
            for task in tasks if task.state.value == "succeeded"
        )
        # Algorithm data outputs are promoted to stable run-level paths only after the Solver
        # attempt passes independent evaluation.  Keep the latest record for each path because a
        # replan/retry may leave older audit rows in the append-only artifact ledger.
        output_artifacts = self._latest_artifacts_by_path(
            [item for item in artifacts if item["kind"] == "output"]
        )
        role_artifacts = [item for item in artifacts if item["kind"] == "role_evidence"]
        role_requirements: list[str] = []
        for task in tasks:
            for rule, relative in self._role_evidence_specs(task.acceptance):
                result_path = str(task.result_path) if task.result_path is not None else ""
                attempt_prefix = result_path.rsplit("/", 1)[0] + "/" if "/" in result_path else ""
                present = any(
                    item.get("task_id") == task.id
                    and item.get("path", "").endswith(f"/{relative}")
                    and (not attempt_prefix or item.get("path", "").startswith(attempt_prefix))
                    for item in role_artifacts
                )
                if not present:
                    role_requirements.append(f"{task.plan_task_id or task.id}/{relative}")
        if role_requirements:
            raise ValueError(
                "run is missing verified role evidence: " + ", ".join(role_requirements[:16])
            )
        contract = self._algorithm_contract(run)
        if contract is not None and contract.outputs:
            missing = [
                output.path
                for output in contract.outputs
                if output.required and output.path not in output_artifacts
            ]
            if missing:
                raise ValueError(
                    "run is missing verified algorithm outputs: " + ", ".join(missing[:16])
                )
        usable = [
            *output_artifacts.values(),
            *role_artifacts,
            *[item for item in artifacts if item["kind"] in {"result", "runtime"}],
        ]
        if not passed or not usable:
            raise ValueError("run has no fully verified artifacts to deliver")
        evidence = tuple(item["path"] for item in usable[:16])
        return PolicyDecision(
            "deliver", "All tasks passed evaluation and have hashed result/runtime/output artifacts", 1.0,
            plan_id=run.current_plan_id, plan_version=run.current_plan_version, evidence=evidence,
        )

    def start(self, goal: str, plan_tasks: list[dict[str, Any]] | None = None) -> Run:
        run = self.create(goal, plan_tasks)
        return self.resume(run.id)

    def create(self, goal: str, plan_tasks: list[dict[str, Any]] | None = None) -> Run:
        """Persist a run and its initial task without executing it."""
        route = self.router.route(goal)
        self._validate_route(route)
        run = self.store.create_run(goal, tasks=plan_tasks, route=route)
        Path(run.workspace).mkdir(parents=True, exist_ok=True)
        return run

    def start_conversational(
        self,
        goal: str,
        compiler: ContractCompiler,
        *,
        workspace: str | Path | None = None,
        compiler_fingerprint: str | None = None,
        run_id: str | None = None,
        plan_factory: Callable[[str, AlgorithmProblemContract], PlanDocument] | None = None,
        execute_plan: bool = True,
    ) -> Run:
        """Compile an algorithm mission and promote the same durable run to a plan.

        The first task is an intake task owned by the controller.  A compiler may pause it through
        ``awaiting_input``; after ``answer_input`` the same method is called again and the task is
        resumed with the verified answer artifact.  Once a contract is accepted, generated plan
        tasks are attached to this run and the ordinary scheduler takes over unless
        ``execute_plan=False`` is used for an explicit orchestration handoff.
        """
        if not hasattr(compiler, "compile") or not callable(compiler.compile):
            raise TypeError("compiler must implement ContractCompiler")
        if run_id is None:
            run = self.create_conversational_run(
                goal, workspace=workspace, compiler_fingerprint=compiler_fingerprint
            )
        else:
            run = self.store.get_run(run_id)
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            if not any(event["type"] == "conversation_started" for event in self.store.list_events(run_id)):
                raise ValueError("run is not a conversational algorithm mission")
            if run.goal != goal.strip():
                raise ValueError("supplied goal does not match the existing conversational run")
            if run.current_plan_id is not None:
                return self.resume(run.id) if execute_plan else run
        return self._compile_conversational_run(
            run,
            compiler,
            compiler_fingerprint,
            plan_factory=plan_factory,
            execute_plan=execute_plan,
        )

    def create_conversational_run(
        self,
        goal: str,
        *,
        workspace: str | Path | None = None,
        compiler_fingerprint: str | None = None,
    ) -> Run:
        """Create an intake-only run for a detached or parent-Agent solve invocation."""
        route = self.router.route(goal)
        self._validate_route(route)
        run = self.store.create_run(
            goal,
            workspace=workspace,
            tasks=[
                {
                    "id": "contract-intake",
                    "title": "Compile algorithm contract",
                    "prompt": goal,
                    "acceptance": None,
                }
            ],
            route=route,
        )
        self.store.append_event(
            run.id,
            "conversation_started",
            {"compiler_fingerprint": compiler_fingerprint},
        )
        return run

    def _compile_conversational_run(
        self,
        run: Run,
        compiler: ContractCompiler,
        compiler_fingerprint: str | None,
        *,
        plan_factory: Callable[[str, AlgorithmProblemContract], PlanDocument] | None = None,
        execute_plan: bool = True,
    ) -> Run:
        """Run one intake attempt and either pause for input or install the generated plan."""
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        task = next(
            (item for item in self.store.list_tasks(run.id) if item.plan_task_id is None), None
        )
        if task is None:
            return self.resume(run.id) if execute_plan else (self.store.get_run(run.id) or run)
        if task.state.value == "waiting":
            return run
        attempt = self.store.claim_task(task.id, "contract-compiler")
        if attempt is None:
            latest = self.store.get_run(run.id)
            return latest or run
        task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        artifacts.write_text(
            f"tasks/{task.id}/{attempt.id}/prompt.md",
            "Compile a strict algorithm contract from the user goal.\n\n" + run.goal,
            task.id,
            kind="prompt",
        )
        answer: str | None = None
        if task.input_answer_path:
            answer_path = (Path(run.workspace) / task.input_answer_path).resolve(strict=False)
            try:
                answer_path.relative_to(Path(run.workspace).resolve())
                answer_payload = json.loads(answer_path.read_text(encoding="utf-8"))
                if isinstance(answer_payload, dict) and isinstance(answer_payload.get("answer"), str):
                    answer = answer_payload["answer"]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                answer = None
            if answer is None:
                error = "input answer artifact is malformed"
                self.store.finish_task(task.id, attempt.id, False, error=error)
                return self.store.settle_run(run.id) or run
        compiler_runtime = getattr(compiler, "runtime", None)
        if compiler_runtime is not None:
            with self._active_lock:
                self._active_runtimes[attempt.id] = compiler_runtime
            set_observer = getattr(compiler_runtime, "set_process_observer", None)
            if callable(set_observer):
                try:
                    set_observer(
                        lambda pid, pgid, attempt_id=attempt.id: self.store.set_attempt_process(
                            attempt_id, pid, pgid
                        )
                    )
                except Exception as observer_error:  # noqa: BLE001 - observer must not block intake
                    del observer_error
        try:
            result = compiler.compile(
                run.goal,
                task_root,
                answer=answer,
                timeout=self.config.runtime_timeout,
            )
            if not self._task_is_running(task.id):
                self._discard_late_result(run.id, task.id, attempt.id)
                return self.store.get_run(run.id) or run
            if not isinstance(result, CompilationResult):
                raise ContractCompilationError("compiler returned an invalid result")
            if result.status == "needs_input":
                question = result.questions[0]
                request_payload = {
                    "status": "awaiting_input",
                    "run_id": run.id,
                    "task_id": task.id,
                    "attempt_id": attempt.id,
                    "question": question.question,
                    "options": list(question.options),
                    "questions": [item.to_dict() for item in result.questions],
                }
                request_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/input-request.json",
                    json.dumps(request_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    task.id,
                    kind="input",
                )
                self._write_compiler_manifest(
                    run,
                    task.id,
                    status="needs_input",
                    compiler_fingerprint=compiler_fingerprint,
                    plan_kind="role_dag" if plan_factory is not None else "legacy",
                    evidence=result.evidence,
                )
                self.store.await_input(
                    task.id,
                    attempt.id,
                    str(request_path.relative_to(Path(run.workspace))),
                    question.question,
                    question.options,
                )
                return self.store.get_run(run.id) or run
            assert result.contract is not None
            contract = result.contract
            plan = result.plan or (plan_factory or build_algorithm_plan)(run.goal, contract)
            if plan.algorithm_problem is None:
                raise ContractCompilationError("generated plan is missing algorithm_problem")
            try:
                attached_contract = AlgorithmProblemContract.from_dict(plan.algorithm_problem)
            except (TypeError, ValueError) as exc:
                raise ContractCompilationError("generated plan contains an invalid algorithm contract") from exc
            if attached_contract.digest() != contract.digest() or plan.goal != run.goal:
                raise ContractCompilationError("generated plan does not match the compiled contract or goal")
            contract_path = artifacts.write_text(
                "solve/contract.json",
                json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                task.id,
                kind="algorithm_contract",
            )
            plan_path = artifacts.write_text(
                "solve/plan.json",
                json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                task.id,
                kind="algorithm_plan",
            )
            decision = PolicyDecision(
                "execute_plan",
                "A strict algorithm contract was compiled from the conversational intake",
                1.0,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                evidence=result.evidence or ("validated contract compiler response",),
                plan=plan.to_dict(),
            )
            self.store.attach_plan_to_run(run.id, plan, decision)
            self._register_algorithm_workspace(run, plan)
            self._write_compiler_manifest(
                run,
                task.id,
                status="compiled",
                compiler_fingerprint=compiler_fingerprint,
                plan_kind="role_dag" if plan_factory is not None else "legacy",
                contract_sha256=contract.digest(),
                plan=plan,
                contract_path=str(contract_path.relative_to(Path(run.workspace))),
                plan_path=str(plan_path.relative_to(Path(run.workspace))),
                evidence=result.evidence,
            )
            self.store.append_event(
                run.id,
                "contract_compiled",
                {
                    "contract_sha256": contract.digest(),
                    "plan_id": plan.plan_id,
                    "plan_version": plan.version,
                    "evidence": list(result.evidence),
                },
                task_id=task.id,
            )
            self.store.finish_task(
                task.id,
                attempt.id,
                True,
                str(contract_path.relative_to(Path(run.workspace))),
            )
            self.store.settle_run(run.id)
            return self.resume(run.id) if execute_plan else (self.store.get_run(run.id) or run)
        except ContractCompilationError as exc:
            error = str(exc)[-2_000:] or "contract compilation failed"
        except Exception as exc:  # noqa: BLE001 - compiler is an untrusted boundary
            error = self._sanitize_error(exc)
        finally:
            if compiler_runtime is not None:
                reset_observer = getattr(compiler_runtime, "set_process_observer", None)
                if callable(reset_observer):
                    try:
                        reset_observer(None)
                    except Exception as observer_error:  # noqa: BLE001 - cleanup must not mask result
                        del observer_error
                with self._active_lock:
                    self._active_runtimes.pop(attempt.id, None)
        self.store.finish_task(task.id, attempt.id, False, error=error)
        settled = self.store.settle_run(run.id)
        return settled or run

    def resume_conversational(
        self,
        run_id: str,
        compiler: ContractCompiler,
        *,
        compiler_fingerprint: str | None = None,
        plan_factory: Callable[[str, AlgorithmProblemContract], PlanDocument] | None = None,
        execute_plan: bool = True,
    ) -> Run:
        """Resume intake or generated tasks; optionally stop after contract attachment."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if not any(event["type"] == "conversation_started" for event in self.store.list_events(run_id)):
            raise ValueError("run is not a conversational algorithm mission")
        if run.current_plan_id is not None:
            return self.resume(run_id) if execute_plan else run
        return self._compile_conversational_run(
            run,
            compiler,
            compiler_fingerprint,
            plan_factory=plan_factory,
            execute_plan=execute_plan,
        )

    def _write_compiler_manifest(
        self,
        run: Run,
        task_id: str,
        *,
        status: str,
        compiler_fingerprint: str | None,
        plan_kind: str = "legacy",
        evidence: tuple[str, ...] = (),
        contract_sha256: str | None = None,
        plan: PlanDocument | None = None,
        contract_path: str | None = None,
        plan_path: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": "1",
            "status": status,
            "goal_sha256": hashlib.sha256(run.goal.encode("utf-8")).hexdigest(),
            "runtime_fingerprint": compiler_fingerprint,
            "plan_kind": plan_kind,
            "evidence": list(evidence),
        }
        if contract_sha256 is not None:
            payload["contract_sha256"] = contract_sha256
        if plan is not None:
            payload.update({"plan_id": plan.plan_id, "plan_version": plan.version})
        if contract_path is not None:
            payload["contract_path"] = contract_path
        if plan_path is not None:
            payload["plan_path"] = plan_path
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        manifest = artifacts.write_text(
            "solve/compiler-manifest.json",
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            task_id,
            kind="compiler_manifest",
        )
        del manifest

    def run_agent(
        self,
        run_id: str,
        *,
        role: str = "solver",
        prompt: str | None = None,
        required_capabilities: tuple[str, ...] | list[str] = (),
        preferred_adapter: str | None = None,
        task_id: str | None = None,
        timeout: float | None = None,
    ) -> tuple[Run, AgentResult]:
        """Delegate one ready task to an explicitly registered Agent adapter.

        This entry point intentionally mirrors the normal scheduler's durable lifecycle while
        keeping the worker ignorant of Store handles.  It is synchronous for library callers; a
        parent process that needs detachment can invoke the JSON ``delegate`` CLI and later use
        ``status``/``resume``.
        """
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError(f"run is already terminal: {run_id}")
        if run.status == RunStatus.RUNNING and self._runner_is_stale(run):
            self.store.recover_running(run_id)
            run = self.store.get_run(run_id)
            if run is None:
                raise ValueError(f"run disappeared while recovering: {run_id}")
        started = time.monotonic()
        budget = run.budget or BudgetSpec()
        task = self.store.get_task(task_id) if task_id else self.store.next_task(run_id)
        if task is None or task.run_id != run_id:
            raise ValueError("run has no ready task to delegate")
        requested = tuple(required_capabilities) or tuple(run.route_required_capabilities)
        try:
            adapter = self.agent_registry.select(role, requested, preferred_adapter)
        except (AgentSelectionError, TypeError, ValueError):
            self.store.append_event(
                run_id,
                "agent_selection_failed",
                {
                    "role": role,
                    "required_capabilities": list(requested)[:64],
                    "preferred_adapter": preferred_adapter,
                },
                task_id=task.id,
            )
            raise
        effective_prompt = prompt if prompt is not None else self._build_task_prompt(run, task)
        if not effective_prompt.strip() or "\x00" in effective_prompt:
            raise ValueError("delegation prompt must be non-empty and NUL-free")
        if len(effective_prompt.encode("utf-8")) > 64 * 1024:
            raise ValueError("delegation prompt exceeds 65536 bytes")
        effective_timeout = self.config.runtime_timeout if timeout is None else timeout
        if (
            isinstance(effective_timeout, bool)
            or not isinstance(effective_timeout, (int, float))
            or effective_timeout <= 0
            or effective_timeout > 24 * 60 * 60
        ):
            raise ValueError("delegation timeout must be between 0 and 86400 seconds")
        self._check_budget(run.id, budget, started, before_claim=True)
        attempt = self.store.claim_task(task.id, adapter.name)
        if attempt is None:
            raise ValueError("task was claimed or cancelled concurrently; retry after inspecting status")
        task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        try:
            self._materialize_task_input_data(run, task_root)
            request = AgentRequest(
                run_id=run.id,
                task_id=task.id,
                role=role,
                prompt=effective_prompt,
                required_capabilities=requested,
                workspace=task_root,
                timeout=effective_timeout,
            )
        except (TypeError, ValueError) as exc:
            error = self._sanitize_error(exc)
            self.store.finish_task(task.id, attempt.id, False, error=error)
            self.store.settle_run(run.id)
            raise AgentInvocationError(error) from exc
        self.store.append_event(
            run.id,
            "agent_selected",
            {
                "attempt_id": attempt.id,
                "adapter": adapter.name,
                "role": role,
                "required_capabilities": list(request.required_capabilities),
            },
            task_id=task.id,
        )
        self.store.append_event(
            run.id,
            "agent_started",
            {"attempt_id": attempt.id, "adapter": adapter.name, "role": role},
            task_id=task.id,
        )
        artifacts.write_text(
            f"tasks/{task.id}/{attempt.id}/prompt.md", effective_prompt, task.id, kind="prompt"
        )
        with self._active_lock:
            self._active_agents[attempt.id] = adapter
        try:
            adapter.set_process_observer(
                lambda pid, pgid: self.store.set_attempt_process(attempt.id, pid, pgid)
            )
            if not self._task_is_running(task.id):
                self._discard_late_result(run.id, task.id, attempt.id)
                raise AgentInvocationError("task was cancelled before agent start")
            result = adapter.run(request)
            if not isinstance(result, AgentResult):
                raise AgentInvocationError("agent returned an invalid result")
            if result.adapter_name != adapter.name or result.role != request.role:
                raise AgentInvocationError("agent result identity does not match the selected adapter")
            if not self._task_is_running(task.id):
                self._discard_late_result(run.id, task.id, attempt.id)
                raise AgentInvocationError("agent result discarded because the task was cancelled")
            result_path = artifacts.write_text(
                f"tasks/{task.id}/{attempt.id}/result.txt", result.text, task.id, kind="result"
            )
            for relative_path in result.artifacts:
                runtime_path = self._runtime_artifact_path(task_root, relative_path)
                artifacts.record(runtime_path, task.id, kind="runtime")
            self._record_role_evidence(run, task, task_root)
            self._check_budget(run.id, budget, started)
            result_payload = {
                "attempt_id": attempt.id,
                "adapter": result.adapter_name,
                "role": result.role,
                "status": result.status,
                "artifacts": list(result.artifacts),
                "metadata": result.metadata,
                "error": result.error,
            }
            self.store.append_event(
                run.id,
                "agent_finished" if result.status == "succeeded" else "agent_failed",
                result_payload,
                task_id=task.id,
            )
            evaluation = self._evaluate(run, task, result.text, task_root)
            evaluation_payload = {
                "attempt_id": attempt.id,
                "passed": evaluation.passed,
                "reason": evaluation.reason,
                "evidence": list(evaluation.evidence),
                "details": evaluation.details,
            }
            self.store.append_event(run.id, "task_evaluated", evaluation_payload, task_id=task.id)
            if result.status != "succeeded":
                error = result.error or f"agent returned {result.status}"
                self.store.finish_task(task.id, attempt.id, False, str(result_path.relative_to(run.workspace)), error)
            elif evaluation.passed:
                self._promote_algorithm_outputs(run, task, task_root)
                self.store.finish_task(task.id, attempt.id, True, str(result_path.relative_to(run.workspace)))
            elif self._can_retry(task.attempts + 1):
                self.store.retry_task(task.id, attempt.id, evaluation.reason)
            else:
                self.store.finish_task(
                    task.id,
                    attempt.id,
                    False,
                    str(result_path.relative_to(run.workspace)),
                    evaluation.reason,
                )
            settled = self.store.settle_run(run.id)
            if settled is None:
                raise ValueError(f"run disappeared while delegating: {run.id}")
            return settled, result
        except BudgetExceeded:
            self.store.settle_run(run.id)
            raise
        except AgentInvocationError as exc:
            error = self._sanitize_error(exc)
            self.store.append_event(
                run.id,
                "agent_failed",
                {"attempt_id": attempt.id, "adapter": adapter.name, "role": role, "error": error},
                task_id=task.id,
            )
            if self._task_is_running(task.id):
                if self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
            self.store.settle_run(run.id)
            raise
        except Exception as exc:
            error = self._sanitize_error(exc)
            self.store.append_event(
                run.id,
                "agent_failed",
                {"attempt_id": attempt.id, "adapter": adapter.name, "role": role, "error": error},
                task_id=task.id,
            )
            if self._task_is_running(task.id):
                if self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
            self.store.settle_run(run.id)
            raise AgentInvocationError(error) from exc
        finally:
            try:
                adapter.set_process_observer(None)
            except Exception as cleanup_error:  # noqa: BLE001 - cleanup must not mask result
                del cleanup_error
            with self._active_lock:
                self._active_agents.pop(attempt.id, None)

    def resume(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run

        self.store.recover_running(run_id)
        run = self.store.get_run(run_id)
        assert run is not None
        started = time.monotonic()
        budget = run.budget or BudgetSpec()
        executor: ThreadPoolExecutor | None = None
        active_attempt_ids: set[str] = set()
        if self.max_workers > 1:
            executor = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix="lunar-worker",
            )
        try:
            while True:
                futures: list[Future[None]] = []
                claimed = 0
                while claimed < self.max_workers:
                    task = self.store.next_task(run_id)
                    if task is None:
                        break
                    self._check_budget(run_id, budget, started, before_claim=True)
                    try:
                        runtime = self._new_runtime()
                    except Exception as exc:  # noqa: BLE001 - factory is a runtime boundary
                        attempt = self.store.claim_task(task.id, getattr(self.runtime, "name", "runtime"))
                        if attempt is not None:
                            claimed += 1
                            self._record_task_failure(run, task, attempt, self._sanitize_error(exc))
                        continue
                    attempt = self.store.claim_task(task.id, getattr(runtime, "name", "runtime"))
                    if attempt is None:
                        continue
                    claimed += 1
                    active_attempt_ids.add(attempt.id)
                    with self._active_lock:
                        self._active_runtimes[attempt.id] = runtime
                    if executor is None:
                        self._execute_task(run, task, attempt, runtime, budget, started)
                    else:
                        futures.append(
                            executor.submit(
                                self._execute_task, run, task, attempt, runtime, budget, started
                            )
                        )
                if not claimed:
                    break
                budget_error: BudgetExceeded | None = None
                for future in futures:
                    try:
                        future.result()
                    except BudgetExceeded as exc:
                        budget_error = budget_error or exc
                with self._active_lock:
                    for attempt_id in active_attempt_ids:
                        self._active_runtimes.pop(attempt_id, None)
                active_attempt_ids.clear()
                if budget_error is not None:
                    raise budget_error
        except BudgetExceeded:
            # The ledger already contains the structured failure; return the failed run handle.
            pass
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            with self._active_lock:
                for attempt_id in active_attempt_ids:
                    self._active_runtimes.pop(attempt_id, None)
            # A synchronous controller has no runner identity; a detached child clears only its
            # own PID so a newer runner cannot be accidentally cleared.
            self.store.clear_runner_process(run_id, os.getpid())
        settled = self.store.settle_run(run_id)
        assert settled is not None
        return settled

    def _new_runtime(self) -> Runtime:
        if self.max_workers > 1:
            assert self.runtime_factory is not None
            return self.runtime_factory()
        return self.runtime

    def _record_task_failure(self, run: Run, task: Any, attempt: Any, error: str) -> None:
        """Persist a failure for a task that could not enter its runtime worker."""
        del run
        if not self._task_is_running(task.id):
            return
        if self._can_retry(task.attempts + 1):
            self.store.retry_task(task.id, attempt.id, error)
        else:
            self.store.finish_task(task.id, attempt.id, False, error=error)

    def _execute_task(
        self,
        run: Run,
        task: Any,
        attempt: Any,
        runtime: Runtime,
        budget: BudgetSpec,
        started: float,
    ) -> None:
        """Execute one claimed task using only its private runtime and callback closures."""
        task_root = Path(run.workspace) / "tasks" / task.id / attempt.id
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        prompt = self._build_task_prompt(run, task)
        artifacts.write_text(
            f"tasks/{task.id}/{attempt.id}/prompt.md", prompt, task.id, kind="prompt"
        )
        with self._active_lock:
            self._active_runtimes[attempt.id] = runtime
        try:
            try:
                self._materialize_task_input_data(run, task_root)
                set_context = getattr(runtime, "set_context", None)
                if callable(set_context):
                    set_context(run.id, task.id, run.goal)
                set_session_path = getattr(runtime, "set_session_path", None)
                if callable(set_session_path):
                    set_session_path(Path(run.workspace) / "sessions" / task.id / "transcript.jsonl")
                set_event_sink = getattr(runtime, "set_event_sink", None)
                if callable(set_event_sink):
                    set_event_sink(
                        lambda event_type, payload, run_id=run.id, task_id=task.id: self.store.append_event(
                            run_id, event_type, payload, task_id=task_id
                        )
                    )
                set_observer = getattr(runtime, "set_process_observer", None)
                if callable(set_observer):
                    set_observer(
                        lambda pid, pgid, attempt_id=attempt.id: self.store.set_attempt_process(
                            attempt_id, pid, pgid
                        )
                    )
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                result = runtime.run(prompt, task_root, self.config.runtime_timeout)
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                self._record_session_artifact(run, task.id, runtime)
                result_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/result.txt", result.text, task.id
                )
                for relative_path in result.artifacts:
                    runtime_path = self._runtime_artifact_path(task_root, relative_path)
                    artifacts.record(runtime_path, task.id, kind="runtime")
                self._record_role_evidence(run, task, task_root)
                self._check_budget(run.id, budget, started)
                evaluation = self._evaluate(run, task, result.text, task_root)
                evaluation_payload = {
                    "attempt_id": attempt.id,
                    "passed": evaluation.passed,
                    "reason": evaluation.reason,
                    "evidence": list(evaluation.evidence),
                    "details": evaluation.details,
                }
                self.store.append_event(run.id, "task_evaluated", evaluation_payload, task_id=task.id)
                evaluation_path = artifacts.safe_path(f"tasks/{task.id}/{attempt.id}/evaluation.json")
                evaluation_path.parent.mkdir(parents=True, exist_ok=True)
                evaluation_path.write_text(
                    json.dumps(evaluation_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                relative_result = str(result_path.relative_to(Path(run.workspace)))
                if evaluation.passed:
                    self._promote_algorithm_outputs(run, task, task_root)
                    self.store.finish_task(task.id, attempt.id, True, relative_result)
                elif self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, evaluation.reason)
                else:
                    self.store.finish_task(task.id, attempt.id, False, relative_result, evaluation.reason)
            except BudgetExceeded:
                raise
            except AgentInputRequired as exc:
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id)
                    return
                self._record_session_artifact(run, task.id, runtime)
                request_payload = {
                    "status": "awaiting_input",
                    "run_id": run.id,
                    "task_id": task.id,
                    "attempt_id": attempt.id,
                    "question": exc.question,
                    "options": list(exc.options),
                }
                request_path = artifacts.write_text(
                    f"tasks/{task.id}/{attempt.id}/input-request.json",
                    json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n",
                    task.id,
                    kind="input",
                )
                self.store.await_input(
                    task.id,
                    attempt.id,
                    str(request_path.relative_to(Path(run.workspace))),
                    exc.question,
                    exc.options,
                )
            except Exception as exc:  # noqa: BLE001 - runtime boundary must persist all failures
                error = self._sanitize_error(exc)
                if self._task_is_running(task.id):
                    self._record_session_artifact(run, task.id, runtime)
                if not self._task_is_running(task.id):
                    self._discard_late_result(run.id, task.id, attempt.id, error)
                elif self._can_retry(task.attempts + 1):
                    self.store.retry_task(task.id, attempt.id, error)
                else:
                    self.store.finish_task(task.id, attempt.id, False, error=error)
        finally:
            if callable(getattr(runtime, "set_event_sink", None)):
                runtime.set_event_sink(None)
            if callable(getattr(runtime, "set_process_observer", None)):
                runtime.set_process_observer(None)
            with self._active_lock:
                self._active_runtimes.pop(attempt.id, None)

    def cancel(self, run_id: str) -> bool:
        cancelled = self.store.cancel_run(run_id)
        if cancelled:
            with self._active_lock:
                runtimes = list(self._active_runtimes.values())
                agents = list(self._active_agents.values())
            seen: set[int] = set()
            cancellables: list[object] = [*runtimes, *agents]
            if not cancellables:
                cancellables = [self.runtime]
            for runtime in cancellables:
                identity = id(runtime)
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    runtime.cancel()
                except Exception as exc:  # noqa: BLE001 - cancellation must continue to all workers
                    # One adapter failing to cancel must not prevent the remaining adapters.
                    del exc
            run = self.store.get_run(run_id)
            if run is not None:
                self._terminate_process_group(run.runner_pid, run.runner_pgid)
                self.store.clear_runner_process(run_id)
        return cancelled

    def recover(self, run_id: str) -> RecoveryProposal:
        """Persist an advisory recovery proposal without changing execution state.

        This is deliberately separate from :meth:`resume`: a parent Agent or owner decides whether
        to apply a patch/replan, answer input, or resume a runtime after inspecting the evidence.
        """
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run: {run_id}")
        tasks = self.store.list_tasks(run.id)
        proposal = self.recovery_policy.propose(
            run, tasks, self.store.list_events(run.id), self.store.pending_input(run.id)
        )
        target_task_id = proposal.task_id or (tasks[0].id if tasks else None)
        if target_task_id is None:
            raise ValueError("run has no task to own the recovery artifact")
        relative_path = f"recovery/proposals/{proposal.fingerprint}.json"
        persisted = proposal.with_artifact_path(relative_path)
        artifacts = ArtifactStore(run.workspace, self.store, run.id)
        if not any(
            item["path"] == relative_path and item["kind"] == "recovery"
            for item in self.store.list_artifacts(run.id)
        ):
            artifacts.write_text(
                relative_path,
                json.dumps(persisted.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                target_task_id,
                kind="recovery",
            )
        self.store.append_event(
            run.id,
            "recovery_proposed",
            {"proposal": persisted.to_dict()},
            task_id=proposal.task_id,
            event_id=proposal.event_id,
        )
        return persisted

    def _task_is_running(self, task_id: str) -> bool:
        task = self.store.get_task(task_id)
        return task is not None and task.state.value == "running"

    @staticmethod
    def _runner_is_stale(run: Run) -> bool:
        """Return whether it is safe for a delegation caller to recover running tasks."""
        if run.runner_pid is None:
            return True
        if run.runner_pid == os.getpid():
            return True
        try:
            os.kill(run.runner_pid, 0)
        except (OSError, ProcessLookupError):
            return True
        return False

    def _validate_route(self, route: RouteDecision) -> None:
        """Reject missing profile configuration before any durable work is created."""
        self.profiles.solver(route.solver_profile)
        if self.evaluator is None:
            self.profiles.evaluator(route.evaluator_profile)

    def _record_session_artifact(self, run: Run, task_id: str, runtime: Runtime | None = None) -> None:
        runtime = runtime or self.runtime
        get_session_path = getattr(runtime, "session_path", None)
        if not callable(get_session_path):
            return
        path = get_session_path()
        if path is None or not Path(path).is_file():
            return
        try:
            relative = str(Path(path).resolve().relative_to(Path(run.workspace).resolve()))
        except ValueError:
            return
        if any(
            artifact["path"] == relative and artifact["kind"] == "session"
            for artifact in self.store.list_artifacts(run.id)
        ):
            return
        ArtifactStore(run.workspace, self.store, run.id).record(path, task_id, kind="session")

    @staticmethod
    def _latest_artifacts_by_path(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Return the newest ledger row for each path without mutating append-only history."""
        latest: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            path = artifact.get("path")
            if isinstance(path, str):
                latest[path] = artifact
        return latest

    def _algorithm_contract(self, run: Run) -> AlgorithmProblemContract | None:
        plan = self.store.get_current_plan(run.id)
        if plan is None or plan.algorithm_problem is None:
            return None
        return AlgorithmProblemContract.from_dict(plan.algorithm_problem)

    def _task_output_specs(self, run: Run, task: Any) -> tuple[OutputSpec, ...]:
        """Return declared outputs for the Solver task, if this run has an algorithm contract.

        Output paths are logical paths relative to an attempt workspace.  Only the built-in
        ``solve``/``solver`` plan roles are allowed to publish them; discovery and verification
        roles may inspect the resulting run-level files but cannot accidentally overwrite them.
        """
        if (task.plan_task_id or task.id) not in {"solve", "solver"}:
            return ()
        contract = self._algorithm_contract(run)
        return contract.outputs if contract is not None else ()

    @staticmethod
    def _role_evidence_specs(value: object) -> tuple[tuple[str, str], ...]:
        """Extract explicitly declared role-evidence paths from a task acceptance contract."""
        found: list[tuple[str, str]] = []

        def visit(item: object) -> None:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except (TypeError, json.JSONDecodeError):
                    return
            if isinstance(item, dict):
                if len(item) == 1:
                    rule, payload = next(iter(item.items()))
                    if rule in {"artifact_valid", "data_profile_valid", "evaluation_report_valid"}:
                        path = payload.get("path") if isinstance(payload, dict) else payload
                        if isinstance(path, str):
                            pair = (rule, path)
                            if pair not in found:
                                found.append(pair)
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
        return tuple(found[:16])

    def _record_role_evidence(self, run: Run, task: Any, task_root: Path) -> tuple[dict[str, Any], ...]:
        """Hash present role hand-off files, including invalid files for retry/audit evidence."""
        specs = self._role_evidence_specs(task.acceptance)
        if not specs:
            return ()
        root = Path(run.workspace).expanduser().resolve(strict=False)
        artifacts = ArtifactStore(root, self.store, run.id)
        recorded: list[dict[str, Any]] = []
        for rule, relative in specs:
            source = self._confined_regular_file(task_root, relative)
            if source is None:
                continue
            size = source.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                raise ArtifactError(f"role evidence exceeds {MAX_ARTIFACT_BYTES} bytes: {relative}")
            artifact_id = artifacts.record(source, task.id, kind="role_evidence")
            recorded.append({"artifact_id": artifact_id, "rule": rule, "path": str(source.relative_to(root)), "size": size})
        if recorded:
            self.store.append_event(
                run.id,
                "role_evidence_recorded",
                {"artifacts": recorded},
                task_id=task.id,
            )
        return tuple(recorded)

    def _materialize_task_input_data(self, run: Run, task_root: Path) -> tuple[str, ...]:
        """Copy hashed run inputs into a private attempt workspace.

        Runtime and Agent adapters are intentionally confined to ``task_root``.  Copying verified
        input artifacts to the same relative ``data/raw/...`` path gives every attempt deterministic
        read access without granting it access to the run ledger or another attempt's files.
        """
        input_artifacts = [
            item
            for item in self.store.list_artifacts(run.id)
            if item["kind"] == "input_data"
        ]
        if len(input_artifacts) > MAX_INPUT_FILES:
            raise ArtifactError(f"run has more than {MAX_INPUT_FILES} staged input files")
        if not input_artifacts:
            return ()
        root = Path(run.workspace).expanduser().resolve(strict=False)
        task_root = task_root.expanduser().resolve(strict=False)
        copied: list[str] = []
        for artifact in input_artifacts:
            relative = artifact.get("path")
            expected_digest = artifact.get("sha256")
            expected_size = artifact.get("size")
            if (
                not isinstance(relative, str)
                or not relative.startswith("data/raw/")
                or not isinstance(expected_digest, str)
                or not isinstance(expected_size, int)
                or expected_size > MAX_INPUT_FILE_BYTES
            ):
                raise ArtifactError("staged input artifact metadata is malformed")
            source = self._confined_regular_file(root, relative)
            if source is None:
                raise ArtifactError(f"staged input is missing or unsafe: {relative}")
            content = source.read_bytes()
            if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
                raise ArtifactError(f"staged input digest does not match the ledger: {relative}")
            target = (task_root / relative).resolve(strict=False)
            try:
                target.relative_to(task_root)
            except ValueError as exc:
                raise ArtifactError(f"staged input escapes task workspace: {relative}") from exc
            if self._raw_path_has_symlink(task_root, target):
                raise ArtifactError(f"staged input target is symlinked: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(content)
            temporary.replace(target)
            copied.append(relative)
        return tuple(copied)

    @staticmethod
    def _raw_path_has_symlink(root: Path, path: Path) -> bool:
        """Check every existing component without following a symlink."""
        current = path
        while True:
            # ``Path.exists`` is false for a dangling symlink; inspect the link itself first so a
            # target cannot be swapped after validation or escape through a broken link.
            if current.is_symlink():
                return True
            if current == root:
                return False
            if current.parent == current:
                return True
            current = current.parent

    def _confined_regular_file(self, root: Path, relative_path: str) -> Path | None:
        """Resolve a regular, non-symlink file below ``root`` or return ``None``."""
        root = root.expanduser().resolve(strict=False)
        if root.is_symlink() or "\x00" in relative_path:
            return None
        raw = root / relative_path
        if self._raw_path_has_symlink(root, raw):
            return None
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            return None
        if not resolved.is_file() or resolved.is_symlink():
            return None
        return resolved

    def _promote_algorithm_outputs(
        self, run: Run, task: Any, task_root: Path
    ) -> tuple[dict[str, Any], ...]:
        """Copy verified Solver data files to stable run-level output paths and hash them.

        The runtime receives an attempt-local workspace so retries and parallel tasks remain
        isolated.  Promotion happens only after the complete evaluation passes, which gives
        callers a stable ``<run>/output/...`` location and prevents unverified files from being
        delivered.  Optional outputs are promoted when present; required outputs must already
        have passed the independent output evaluator.
        """
        specs = self._task_output_specs(run, task)
        if not specs:
            return ()
        root = Path(run.workspace).expanduser().resolve(strict=False)
        promoted: list[dict[str, Any]] = []
        artifacts = ArtifactStore(root, self.store, run.id)
        for output in specs:
            source = self._confined_regular_file(task_root, output.path)
            if source is None:
                if output.required:
                    raise ArtifactError(f"required algorithm output is missing: {output.path}")
                continue
            # Keep the same bounded inspection/ledger limit used by output_valid.  This prevents
            # a successful model turn from smuggling an unbounded binary into the run archive.
            size = source.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                raise ArtifactError(
                    f"algorithm output exceeds {MAX_ARTIFACT_BYTES} bytes: {output.path}"
                )
            target = self._confined_output_target(root, output.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(source.read_bytes())
            temporary.replace(target)
            artifact_id = artifacts.record(target, task.id, kind="output")
            promoted.append(
                {
                    "artifact_id": artifact_id,
                    "path": output.path,
                    "format": output.format,
                    "fields": list(output.fields),
                    "required": output.required,
                    "size": size,
                }
            )
        if promoted:
            self.store.append_event(
                run.id,
                "algorithm_outputs_promoted",
                {"outputs": promoted},
                task_id=task.id,
            )
        return tuple(promoted)

    def _confined_output_target(self, root: Path, relative_path: str) -> Path:
        """Resolve a run-level output target while rejecting symlinked directories."""
        root = root.expanduser().resolve(strict=False)
        raw = root / relative_path
        output_root = root / "output"
        if self._raw_path_has_symlink(root, output_root) or self._raw_path_has_symlink(root, raw):
            raise ArtifactError(f"algorithm output path is symlinked: {relative_path}")
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
            resolved.relative_to(output_root.resolve(strict=False))
        except ValueError as exc:
            raise ArtifactError(f"algorithm output escapes run workspace: {relative_path}") from exc
        if resolved == output_root:
            raise ArtifactError("algorithm output path must name a file")
        return resolved

    @staticmethod
    def _acceptance_output_specs(value: object) -> dict[str, tuple[str, tuple[str, ...]]]:
        specs: dict[str, tuple[str, tuple[str, ...]]] = {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return specs
        if isinstance(value, dict):
            if set(value) == {"output_valid"} and isinstance(value["output_valid"], dict):
                payload = value["output_valid"]
                path = payload.get("path")
                output_format = payload.get("format")
                fields = payload.get("fields")
                if (
                    isinstance(path, str)
                    and isinstance(output_format, str)
                    and isinstance(fields, list)
                    and all(isinstance(field, str) for field in fields)
                ):
                    specs[path] = (output_format, tuple(fields))
            for child in value.values():
                specs.update(LocalController._acceptance_output_specs(child))
        elif isinstance(value, list):
            for child in value:
                specs.update(LocalController._acceptance_output_specs(child))
        return specs

    def _evaluate(self, run: Run, task: Any, result: str, workspace: Path) -> Evaluation:
        evaluator = self.evaluator or self.profiles.evaluator(run.evaluator_profile or "general")
        base = evaluator.evaluate(result, workspace)
        criterion = acceptance_evaluator(task.acceptance)
        output_specs = self._task_output_specs(run, task)
        declared_in_acceptance = self._acceptance_output_specs(task.acceptance)
        output_specs_to_check = tuple(
            output
            for output in output_specs
            if declared_in_acceptance.get(output.path)
            != (output.format, tuple(output.fields))
            and (
                output.required
                or self._confined_regular_file(workspace, output.path) is not None
            )
        )
        output_criterion = None
        if output_specs_to_check:
            output_rules = [
                {
                    "output_valid": {
                        "path": output.path,
                        "format": output.format,
                        "fields": list(output.fields),
                    }
                }
                for output in output_specs_to_check
            ]
            output_criterion = acceptance_evaluator(
                output_rules[0] if len(output_rules) == 1 else {"all": output_rules}
            )
        if criterion is None and output_criterion is None:
            return base
        acceptance = criterion.evaluate(result, workspace) if criterion is not None else None
        outputs = output_criterion.evaluate(result, workspace) if output_criterion is not None else None
        checks = [item for item in (acceptance, outputs) if item is not None]
        evidence = tuple(base.evidence) + tuple(
            evidence_item for item in checks for evidence_item in item.evidence
        )
        details: dict[str, object] = {"base": base.details}
        if acceptance is not None:
            details["acceptance"] = acceptance.details
        if outputs is not None:
            details["outputs"] = outputs.details
        if base.passed and all(item.passed for item in checks):
            reasons = "; ".join([base.reason, *(item.reason for item in checks)])
            return Evaluation(True, evidence, reasons, details)
        reasons = [
            reason
            for passed, reason in [
                (base.passed, base.reason),
                *((item.passed, item.reason) for item in checks),
            ]
            if not passed
        ]
        return Evaluation(False, evidence, "; ".join(reasons), details)

    def _check_budget(self, run_id: str, budget: BudgetSpec, started: float, *, before_claim: bool = False) -> None:
        tasks = self.store.list_tasks(run_id)
        attempts = sum(task.attempts for task in tasks)
        if len(tasks) > budget.max_tasks:
            self._budget_fail(run_id, "max_tasks", len(tasks), budget.max_tasks)
        if before_claim and attempts >= budget.max_attempts:
            self._budget_fail(run_id, "max_attempts", attempts, budget.max_attempts)
        elapsed = time.monotonic() - started
        if elapsed > budget.max_runtime_seconds:
            self._budget_fail(run_id, "max_runtime_seconds", elapsed, budget.max_runtime_seconds)
        tool_steps = sum(1 for event in self.store.list_events(run_id) if event["type"] == "agent_tool_result")
        if tool_steps > budget.max_tool_steps:
            self._budget_fail(run_id, "max_tool_steps", tool_steps, budget.max_tool_steps)
        artifact_bytes = sum(int(item["size"]) for item in self.store.list_artifacts(run_id))
        if artifact_bytes > budget.max_artifact_bytes:
            self._budget_fail(run_id, "max_artifact_bytes", artifact_bytes, budget.max_artifact_bytes)

    def _budget_fail(self, run_id: str, limit: str, actual: float, maximum: float) -> None:
        reason = str(BudgetExceeded(limit, actual, maximum))
        self.store.fail_budget(run_id, limit, actual, maximum, reason)
        raise BudgetExceeded(limit, actual, maximum)

    def _discard_late_result(
        self, run_id: str, task_id: str, attempt_id: str, error: str | None = None
    ) -> None:
        run = self.store.get_run(run_id)
        if run is not None:
            for relative_path in self.store.discard_attempt_outputs(run_id, task_id, attempt_id):
                path = (Path(run.workspace) / relative_path).resolve(strict=False)
                try:
                    path.relative_to(Path(run.workspace).resolve())
                    path.unlink(missing_ok=True)
                except (OSError, ValueError):
                    # The ledger is authoritative; a file disappearing concurrently is harmless.
                    pass
        self.store.append_event(
            run_id,
            "task_result_discarded",
            {
                "attempt_id": attempt_id,
                "reason": "run_cancelled_or_task_no_longer_running",
                "error": error,
            },
            task_id=task_id,
        )

    def _build_task_prompt(self, run: Run, task: Any) -> str:
        dependencies = self.store.dependency_artifacts(task.id)
        staged_inputs = [
            item["path"]
            for item in self.store.list_artifacts(run.id)
            if item["kind"] == "input_data" and isinstance(item.get("path"), str)
        ][:MAX_INPUT_FILES]
        answer_path = task.input_answer_path
        answer_content = ""
        if answer_path:
            candidate = (Path(run.workspace) / answer_path).resolve(strict=False)
            try:
                candidate.relative_to(Path(run.workspace).resolve())
                if candidate.is_file() and candidate.stat().st_size <= 20_000:
                    answer_content = candidate.read_text(encoding="utf-8")[:8_000]
            except (OSError, UnicodeDecodeError, ValueError):
                answer_content = "<answer artifact could not be read>"
        output_specs = self._task_output_specs(run, task)
        input_instructions: list[str] = []
        if staged_inputs:
            input_instructions = [
                "Staged input data (read-only copies are available at these task-relative paths):"
            ]
            input_instructions.extend(f"- {path}" for path in staged_inputs)
        output_instructions: list[str] = []
        if output_specs:
            output_instructions = [
                "Declared algorithm data outputs (write these files; a prose answer alone is not sufficient):"
            ]
            output_instructions.extend(
                "- {path} | format={format} | fields={fields} | {required}".format(
                    path=output.path,
                    format=output.format,
                    fields=", ".join(output.fields) if output.fields else "untyped",
                    required="required" if output.required else "optional",
                )
                for output in output_specs
            )
        role_evidence_specs = self._role_evidence_specs(task.acceptance)
        envelope_instructions: list[str] = []
        if output_specs or role_evidence_specs:
            envelope_instructions = [
                "If this runtime cannot call file tools, you may return one strict JSON artifact envelope instead:",
                '{"text":"...", "artifacts":[{"path":"relative/path", "content":"UTF-8 text"}]}.',
                "Use only the declared relative paths; the controller will validate each file before delivery.",
            ]
            if role_evidence_specs:
                envelope_instructions.append(
                    "Declared role hand-off paths: "
                    + ", ".join(path for _, path in role_evidence_specs)
                    + "."
                )
        if not dependencies and not answer_content:
            sections = [*input_instructions, *output_instructions, *envelope_instructions, task.prompt]
        else:
            sections = [*input_instructions, *output_instructions, *envelope_instructions, task.prompt]
            if answer_content:
                sections.extend(
                    [
                        "",
                        "User/parent-Agent answer (from a verified run-relative artifact):",
                        answer_content,
                    ]
                )
            if dependencies:
                sections.extend(["", "Verified dependency artifacts (run-relative paths):"])
                for artifact in dependencies:
                    relative = str(artifact["path"])
                    sections.append(f"- task {artifact['task_id']}: {relative}")
                    artifact_path = Path(run.workspace) / relative
                    if artifact_path.is_file() and artifact_path.stat().st_size <= 20_000:
                        try:
                            content = artifact_path.read_text(encoding="utf-8")
                        except UnicodeDecodeError:
                            content = "<binary artifact; read it from the path>"
                        sections.extend(["  preview:", content[:8_000]])
        feedback = self._retry_feedback(run.id, task)
        if feedback:
            sections.extend(["", feedback])
        return "\n".join(sections)

    def _retry_feedback(self, run_id: str, task: Any) -> str | None:
        """Render bounded, task-scoped evidence for an attempt after the first one."""
        # The scheduler passes the task snapshot captured immediately before the next claim.
        # Therefore ``attempts == 1`` means the prompt belongs to attempt two and must include
        # feedback from attempt one.
        if getattr(task, "attempts", 0) < 1:
            return None
        latest: dict[str, Any] | None = None
        try:
            events = self.store.list_events(run_id)
        except Exception:  # noqa: BLE001 - legacy/corrupt evidence must not block retry
            events = []
        for event in reversed(events):
            if event.get("task_id") != task.id or event.get("type") != "task_evaluated":
                continue
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("passed") is False:
                latest = payload
                break
        previous_attempt = int(task.attempts)
        if latest is None:
            return (
                f"Retry feedback from the previous attempt (attempt {previous_attempt}):\n"
                "- source: runtime_failure\n"
                "- status: failed\n"
                "- instruction: The previous attempt did not complete successfully. Inspect the "
                "task workspace, retry the requested work, and return a complete result."
            )
        rules = self._failed_acceptance_rules(latest.get("details"))
        evidence = ["evaluation_failed"]
        if rules:
            evidence.append("acceptance_check_failed")
            evidence.extend(f"acceptance_rule:{rule}" for rule in rules)
        evidence = list(dict.fromkeys(evidence))[: self._MAX_RETRY_FEEDBACK_VALUES]
        lines = [
            f"Retry feedback from the previous verified attempt (attempt {previous_attempt}):",
            "- source: evaluation",
            "- status: failed",
            f"- evidence: {', '.join(evidence)}",
            (
                "- instruction: Correct the verified failure and produce a complete result. Do not "
                "claim success until the required artifacts satisfy the task acceptance checks."
            ),
        ]
        rendered = "\n".join(lines)
        return rendered[: self._MAX_RETRY_FEEDBACK_BYTES]

    @classmethod
    def _failed_acceptance_rules(cls, details: object) -> tuple[str, ...]:
        found: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                rule = value.get("rule")
                if rule in cls._RETRY_FEEDBACK_RULES and value.get("passed") is False:
                    assert isinstance(rule, str)
                    if rule not in found:
                        found.append(rule)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        if isinstance(details, dict):
            visit(details.get("acceptance"))
            visit(details.get("outputs"))
        return tuple(found[: cls._MAX_RETRY_FEEDBACK_VALUES])

    @staticmethod
    def _runtime_artifact_path(task_root: Path, relative_path: str) -> Path:
        candidate = (task_root / relative_path).resolve(strict=False)
        try:
            candidate.relative_to(task_root.resolve())
        except ValueError as exc:
            raise ArtifactError(f"runtime artifact escapes task workspace: {relative_path}") from exc
        return candidate

    @staticmethod
    def _terminate_process_group(pid: int | None, pgid: int | None) -> None:
        if not pid or pid <= 1 or pid == os.getpid():
            return
        try:
            current_pgid = os.getpgrp()
        except OSError:
            current_pgid = None
        if pgid and pgid > 1 and pgid != current_pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
                return
            except (ProcessLookupError, PermissionError):
                pass
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def _can_retry(self, attempts_after_current: int) -> bool:
        return attempts_after_current < self.config.max_retries

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        if isinstance(error, RuntimeExecutionError):
            return str(error)[-2000:]
        return f"{type(error).__name__}: {str(error)[-1800:]}"
