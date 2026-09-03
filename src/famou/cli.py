"""Command-line interface for the standalone local controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

from .agent_evolution import (
    AgentCandidateEvaluator,
    AgentCandidateGenerator,
    AgentEvaluatorEnsemble,
    AgentPortfolioGenerator,
)
from .agent_loop import AgentLoopRuntime, HermesSessionRuntime
from .agents import (
    DEFAULT_RUNTIME_CAPABILITIES,
    AgentError,
    AgentRegistry,
    CommandAgentAdapter,
    RuntimeAgentAdapter,
)
from .algorithm import MAX_INPUT_FILE_BYTES, MAX_INPUT_FILES, AlgorithmProblemContract
from .artifacts import ArtifactStore
from .benchmark import BenchmarkConfig, BenchmarkRunner
from .budget import BudgetSpec
from .config import Config
from .controller import LocalController
from .conversational import RuntimeContractCompiler, build_algorithm_role_plan
from .evolution import (
    CommandCandidateEvaluator,
    CommandCandidateGenerator,
    CommandCandidateRunner,
    EvolutionConfig,
    EvolutionError,
    ExecutionAwareCandidateEvaluator,
)
from .memory import MemoryStore
from .models import Run
from .policy import MasterPolicy, PlanDocument, PlanPatch
from .runtime import OpenAICompatibleRuntime, build_runtime
from .store import Store
from .tools import LocalToolRegistry


def _add_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--home",
        default=None,
        help="local state directory (default: FAMOU_HOME or .famou)",
    )


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON value on stdout",
    )


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runtime",
        choices=("mock", "subprocess", "openai-compatible"),
        default="mock",
    )
    parser.add_argument("--command", dest="runtime_command", help="explicit subprocess command")
    parser.add_argument("--endpoint", help="OpenAI-compatible chat endpoint URL")
    parser.add_argument("--model", help="model name for the OpenAI-compatible runtime")
    parser.add_argument(
        "--api-key",
        dest="api_key",
        help="optional model API key (prefer FAMOU_API_KEY to avoid shell history)",
    )
    parser.add_argument(
        "--agent-loop",
        "--hermes-session",
        action="store_true",
        help="run a continuous Hermes-inspired tool session (requires openai-compatible runtime)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=40,
        help="maximum tool calls in an agent loop (default: 40)",
    )
    parser.add_argument(
        "--allow-exec",
        action="store_true",
        help="expose the no-shell run_command tool to an agent loop",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="opt in to durable memory tools for this model session",
    )
    parser.add_argument(
        "--session-history",
        action="store_true",
        help="persist and replay a bounded local transcript across retries/resume",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="maximum local task workers (default: 1)",
    )


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        dest="input_files",
        action="append",
        default=[],
        metavar="SOURCE[=DEST]",
        help=(
            "stage a local data file under data/raw (destination defaults to its basename; "
            "repeat for multiple files)"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="famou",
        description="Standalone local Famou agent controller",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a local state directory")
    _add_home(init_parser)
    _add_json(init_parser)

    run_parser = subparsers.add_parser("run", help="start and execute a goal")
    run_parser.add_argument("goal", nargs="?", help="user goal, or '-' to read it from stdin")
    run_parser.add_argument("--plan", type=Path, help="JSON plan file containing goal and tasks")
    _add_runtime_options(run_parser)
    _add_input_options(run_parser)
    run_parser.add_argument(
        "--detach",
        action="store_true",
        help="return a run ID immediately and execute it in a local background process",
    )
    _add_home(run_parser)
    _add_json(run_parser)

    solve_parser = subparsers.add_parser(
        "solve", help="compile a conversational algorithm mission and execute its plan"
    )
    solve_parser.add_argument("goal", nargs="?", help="algorithm objective, or '-' to read stdin")
    solve_parser.add_argument("--workspace", type=Path, help="run workspace (default: a new local run)")
    solve_parser.add_argument("--resume", action="store_true", help="resume a conversational run")
    solve_parser.add_argument("--run-id", help="existing run ID (required with --resume)")
    solve_parser.add_argument(
        "--detach", action="store_true", help="return a run ID and compile/execute in the background"
    )
    solve_parser.add_argument(
        "--role-dag",
        action="store_true",
        help="use the five-stage DataDiscovery/Formulator/Solver/Evaluator/Reviewer workflow",
    )
    solve_parser.add_argument(
        "--evolve",
        action="store_true",
        help="handoff the compiled contract to a linked local evolution run",
    )
    solve_parser.add_argument(
        "--strategy",
        choices=("loop", "population", "openevolve"),
        help="evolution strategy when --evolve is enabled (default: contract strategy)",
    )
    solve_parser.add_argument(
        "--openevolve-command",
        help="explicit OpenEvolve executable for --evolve --strategy openevolve",
    )
    solve_parser.add_argument("--max-rounds", type=int)
    solve_parser.add_argument("--stagnation-rounds", type=int)
    solve_parser.add_argument("--population-size", type=int)
    solve_parser.add_argument("--offspring-per-iteration", type=int)
    solve_parser.add_argument("--islands", type=int)
    solve_parser.add_argument("--migration-interval", type=int)
    solve_parser.add_argument("--migration-rate", type=float)
    solve_parser.add_argument("--seed", type=int)
    solve_parser.add_argument("--timeout", type=float)
    _add_runtime_options(solve_parser)
    _add_input_options(solve_parser)
    _add_home(solve_parser)
    _add_json(solve_parser)

    delegate_parser = subparsers.add_parser(
        "delegate", help="delegate one durable task to an explicit local Agent command"
    )
    delegate_parser.add_argument("prompt", nargs="?", help="task prompt; omit when using --run-id")
    delegate_parser.add_argument(
        "--run-id", help="delegate the next ready task in an existing run"
    )
    delegate_parser.add_argument("--task-id", help="specific task ID in an existing run")
    delegate_parser.add_argument(
        "--agent-command",
        required=True,
        help="explicit command (first token must be an absolute executable path)",
    )
    delegate_parser.add_argument("--agent-name", default="command")
    delegate_parser.add_argument("--agent-role", default="solver")
    delegate_parser.add_argument(
        "--capability",
        dest="capabilities",
        action="append",
        default=[],
        help="required worker capability; may be supplied more than once",
    )
    delegate_parser.add_argument("--preferred-agent")
    delegate_parser.add_argument("--timeout", type=float, default=None)
    delegate_parser.add_argument(
        "--detach",
        action="store_true",
        help="return a run ID immediately and execute delegation in a local child process",
    )
    _add_home(delegate_parser)
    _add_json(delegate_parser)

    resume_parser = subparsers.add_parser("resume", help="recover and continue a run")
    resume_parser.add_argument("run_id")
    _add_runtime_options(resume_parser)
    _add_home(resume_parser)
    _add_json(resume_parser)

    evolve_parser = subparsers.add_parser("evolve", help="run a local algorithm evolution strategy")
    evolve_parser.add_argument("contract", type=Path, help="algorithm problem contract JSON")
    evolve_parser.add_argument("--workspace", type=Path, help="run workspace (default: a new local run)")
    evolve_parser.add_argument("--resume", action="store_true", help="resume an existing strategy run")
    evolve_parser.add_argument("--run-id", help="existing evolution run ID (required with --resume)")
    evolve_parser.add_argument("--detach", action="store_true", help="return an evolution run ID and execute in the background")
    evolve_parser.add_argument("--strategy", choices=("loop", "population", "openevolve"), help="override the contract strategy")
    evolve_parser.add_argument("--generator-command", help="explicit generator command; receives a request JSON path")
    evolve_parser.add_argument("--agent-command", help="explicit Agent command used as candidate generator")
    evolve_parser.add_argument(
        "--agent-portfolio-command",
        dest="agent_portfolio_commands",
        action="append",
        default=[],
        help="repeatable explicit solver Agent command for a deterministic portfolio",
    )
    evolve_parser.add_argument(
        "--agent-runtime",
        choices=("mock", "subprocess", "openai-compatible"),
        help="use a repository-owned runtime for any unbound solver/evaluator seam",
    )
    evolve_parser.add_argument(
        "--agent-runtime-command",
        help="runtime subprocess command (used with --agent-runtime subprocess)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-endpoint",
        help="OpenAI-compatible endpoint (used with --agent-runtime openai-compatible)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-model",
        help="OpenAI-compatible model name (used with --agent-runtime openai-compatible)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-api-key",
        help="optional runtime API key; detached runs pass it via FAMOU_AGENT_RUNTIME_API_KEY",
    )
    evolve_parser.add_argument(
        "--agent-runtime-loop",
        action="store_true",
        help="wrap an OpenAI-compatible evolution runtime in the bounded tool-capable Agent loop",
    )
    evolve_parser.add_argument(
        "--agent-runtime-max-steps",
        type=int,
        default=40,
        help="maximum model tool calls per evolution Agent invocation (default: 40)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-allow-exec",
        action="store_true",
        help="allow no-shell command execution inside the evolution Agent loop",
    )
    evolve_parser.add_argument(
        "--agent-runtime-memory",
        action="store_true",
        help="enable explicit durable memory tools inside the evolution Agent loop",
    )
    evolve_parser.add_argument(
        "--agent-runtime-session-history",
        action="store_true",
        help="persist a bounded transcript in each evolution Agent workspace",
    )
    evolve_parser.add_argument(
        "--candidate-runner-command",
        help="explicit command that runs each candidate before evaluator-command",
    )
    evolve_parser.add_argument("--agent-name", default="evolution-agent")
    evolve_parser.add_argument("--agent-role", default="solver")
    evolve_parser.add_argument(
        "--agent-capability",
        dest="agent_capabilities",
        action="append",
        default=[],
        help="required Agent capability; may be supplied more than once",
    )
    evolve_parser.add_argument("--evaluator-command", help="explicit evaluator command; receives a candidate path")
    evolve_parser.add_argument(
        "--evaluator-agent-command",
        help="explicit evaluator Agent command returning an EvaluationReport JSON object",
    )
    evolve_parser.add_argument(
        "--evaluator-portfolio-command",
        dest="evaluator_portfolio_commands",
        action="append",
        default=[],
        help="repeatable explicit evaluator Agent command for a consensus portfolio",
    )
    evolve_parser.add_argument("--evaluator-agent-name", default="evolution-evaluator")
    evolve_parser.add_argument("--evaluator-agent-role", default="evaluator")
    evolve_parser.add_argument(
        "--evaluator-agent-capability",
        dest="evaluator_agent_capabilities",
        action="append",
        default=[],
        help="required evaluator Agent capability; may be supplied more than once",
    )
    evolve_parser.add_argument("--openevolve-command", help="explicit OpenEvolve command; receives a generated config path")
    evolve_parser.add_argument("--max-rounds", type=int)
    evolve_parser.add_argument("--stagnation-rounds", type=int)
    evolve_parser.add_argument("--population-size", type=int, default=8)
    evolve_parser.add_argument("--offspring-per-iteration", type=int, default=1)
    evolve_parser.add_argument("--islands", type=int, default=1)
    evolve_parser.add_argument("--migration-interval", type=int, default=0)
    evolve_parser.add_argument("--migration-rate", type=float, default=0.1)
    evolve_parser.add_argument("--seed", type=int)
    evolve_parser.add_argument("--timeout", type=float, default=900.0)
    _add_home(evolve_parser)
    _add_json(evolve_parser)

    benchmark_parser = subparsers.add_parser(
        "benchmark", help="compare native evolution strategies on one local contract"
    )
    benchmark_parser.add_argument("contract", type=Path, help="algorithm problem contract JSON")
    benchmark_parser.add_argument(
        "--strategy",
        dest="strategies",
        action="append",
        choices=("loop", "population", "openevolve"),
        help="strategy to compare; repeat for order (default: loop and population)",
    )
    benchmark_parser.add_argument("--workspace", type=Path, help="new benchmark workspace")
    benchmark_parser.add_argument(
        "--generator-command", help="explicit generator command for native strategies"
    )
    benchmark_parser.add_argument(
        "--evaluator-command", help="explicit evaluator command"
    )
    benchmark_parser.add_argument(
        "--openevolve-command", help="explicit OpenEvolve command for the openevolve strategy"
    )
    benchmark_parser.add_argument(
        "--agent-runtime",
        choices=("mock", "subprocess", "openai-compatible"),
        help="use a repository-owned runtime for native solver/evaluator roles",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-command",
        help="runtime subprocess command (used with --agent-runtime subprocess)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-endpoint",
        help="OpenAI-compatible endpoint (used with --agent-runtime openai-compatible)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-model",
        help="OpenAI-compatible model name (used with --agent-runtime openai-compatible)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-api-key",
        help="optional runtime API key; prefer FAMOU_AGENT_RUNTIME_API_KEY",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-loop",
        action="store_true",
        help="wrap an OpenAI-compatible runtime in the bounded tool-capable loop",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-max-steps",
        type=int,
        default=40,
        help="maximum model tool calls per runtime invocation (default: 40)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-allow-exec",
        action="store_true",
        help="allow no-shell command execution inside the runtime loop",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-memory",
        action="store_true",
        help="enable explicit durable memory tools inside the runtime loop",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-session-history",
        action="store_true",
        help="persist a bounded transcript in each runtime workspace",
    )
    benchmark_parser.add_argument("--max-rounds", type=int)
    benchmark_parser.add_argument("--stagnation-rounds", type=int)
    benchmark_parser.add_argument("--population-size", type=int, default=8)
    benchmark_parser.add_argument("--offspring-per-iteration", type=int, default=1)
    benchmark_parser.add_argument("--islands", type=int, default=1)
    benchmark_parser.add_argument("--migration-interval", type=int, default=0)
    benchmark_parser.add_argument("--migration-rate", type=float, default=0.1)
    benchmark_parser.add_argument("--seed", type=int)
    benchmark_parser.add_argument("--timeout", type=float, default=900.0)
    _add_home(benchmark_parser)
    _add_json(benchmark_parser)

    answer_parser = subparsers.add_parser("answer", help="answer a pending agent question and resume")
    answer_parser.add_argument("run_id")
    answer_parser.add_argument("answer", nargs="?", help="answer text, or '-' to read stdin")
    _add_runtime_options(answer_parser)
    _add_home(answer_parser)
    _add_json(answer_parser)

    for name, help_text in (
        ("status", "inspect a run"),
        ("events", "inspect run events"),
        ("cancel", "cancel a run"),
        ("recover", "propose an evidence-guided recovery action"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument("run_id")
        _add_home(command_parser)
        _add_json(command_parser)
    memory_parser = subparsers.add_parser("memory", help="inspect explicit local memory")
    memory_parser.add_argument("query", nargs="?", help="optional lexical recall query")
    memory_parser.add_argument("--scope", help="limit results to global or run:<run-id>")
    memory_parser.add_argument("--limit", type=int, default=20)
    _add_home(memory_parser)
    _add_json(memory_parser)

    decide_parser = subparsers.add_parser("decide", help="classify a goal with Master policy")
    decide_parser.add_argument("goal", nargs="?", help="goal, or '-' to read stdin")
    _add_home(decide_parser)
    _add_json(decide_parser)

    plan_parser = subparsers.add_parser("plan", help="create or inspect a versioned plan")
    plan_parser.add_argument("target", help="plan JSON path to create, or run ID to inspect")
    plan_parser.add_argument("plan_file", nargs="?", help="optional plan JSON path")
    _add_runtime_options(plan_parser)
    _add_home(plan_parser)
    _add_json(plan_parser)

    for name, help_text in (("patch", "patch the current plan"), ("replan", "create a new plan revision")):
        revision_parser = subparsers.add_parser(name, help=help_text)
        revision_parser.add_argument("run_id")
        revision_parser.add_argument("plan_file", type=Path)
        _add_home(revision_parser)
        _add_json(revision_parser)

    deliver_parser = subparsers.add_parser("deliver", help="return verified run artifacts")
    deliver_parser.add_argument("run_id")
    _add_home(deliver_parser)
    _add_json(deliver_parser)
    return parser


def _config(args: argparse.Namespace) -> Config:
    config = Config.from_env(args.home)
    config.ensure()
    Store(config.database).initialize()
    return config


def _controller(args: argparse.Namespace, config: Config) -> LocalController:
    def make_runtime():
        runtime = build_runtime(
            args.runtime,
            getattr(args, "runtime_command", None),
            getattr(args, "endpoint", None),
            getattr(args, "model", None),
            getattr(args, "api_key", None),
        )
        if getattr(args, "agent_loop", False):
            if not isinstance(runtime, OpenAICompatibleRuntime):
                raise ValueError("--agent-loop requires --runtime openai-compatible")
            memory = MemoryStore(config.database) if getattr(args, "memory", False) else None
            tools = LocalToolRegistry(
                allow_exec=getattr(args, "allow_exec", False),
                memory=memory,
                redactions=(runtime.api_key,) if runtime.api_key else (),
            )
            runtime = HermesSessionRuntime(
                runtime,
                tools=tools,
                max_steps=getattr(args, "max_steps", 40),
                memory=memory,
                session_history=getattr(args, "session_history", False),
            )
        return runtime

    workers = getattr(args, "workers", 1)
    runtime = make_runtime()
    return LocalController(
        config,
        runtime,
        runtime_factory=make_runtime if workers > 1 else None,
        max_workers=workers,
    )


def _load_plan(path: Path, goal_override: str | None) -> tuple[str, list[dict[str, object]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read plan {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise TypeError("plan must be a JSON object")
    plan_goal = goal_override or payload.get("goal")
    if not isinstance(plan_goal, str) or not plan_goal.strip():
        raise ValueError("plan requires a non-empty goal (or a positional goal override)")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise TypeError("plan requires a tasks array")
    return plan_goal, tasks


def _load_plan_document(path: Path, goal_override: str | None = None) -> PlanDocument:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read plan {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan is not valid JSON: {exc.msg}") from exc
    if goal_override and isinstance(payload, dict):
        payload = {**payload, "goal": goal_override}
    return PlanDocument.from_dict(payload)


def _detach(
    config: Config,
    args: argparse.Namespace,
    goal: str,
    plan_tasks: list[dict[str, object]] | None = None,
) -> object:
    controller = _controller(args, config)
    run = controller.create(goal, plan_tasks)
    staged_inputs = _stage_input_files(
        run, controller.store, getattr(args, "input_files", None)
    )
    log_path = Path(run.workspace) / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "famou",
        "resume",
        run.id,
        "--runtime",
        args.runtime,
        "--home",
        str(config.home),
        "--json",
        "--workers",
        str(args.workers),
    ]
    if args.runtime_command:
        command.extend(("--command", args.runtime_command))
    if args.endpoint:
        command.extend(("--endpoint", args.endpoint))
    if args.model:
        command.extend(("--model", args.model))
    if args.agent_loop:
        command.append("--agent-loop")
        command.extend(("--max-steps", str(args.max_steps)))
    if args.allow_exec:
        command.append("--allow-exec")
    if args.memory:
        command.append("--memory")
    if args.session_history:
        command.append("--session-history")
    child_env = None
    if args.api_key is not None:
        child_env = os.environ.copy()
        child_env["FAMOU_API_KEY"] = args.api_key
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=child_env,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            controller.store.set_runner_process(run.id, pid, pgid)
            latest = controller.store.get_run(run.id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                controller.store.clear_runner_process(run.id)
    except OSError:
        controller.cancel(run.id)
        raise
    return {
        "run_id": run.id,
        "status": "pending",
        "workspace": str(run.workspace),
        "plan": bool(plan_tasks),
        "workers": args.workers,
        "input_data": list(staged_inputs),
    }


def _print_status(config: Config, run_id: str) -> int:
    store = Store(config.database)
    run = store.get_run(run_id)
    if run is None:
        print(f"unknown run: {run_id}", file=sys.stderr)
        return 2
    print(f"run_id: {run.id}")
    print(f"status: {run.status.value}")
    print(f"goal: {run.goal}")
    print(f"workspace: {run.workspace}")
    if run.runner_pid:
        print(f"runner: pid={run.runner_pid} pgid={run.runner_pgid}")
    pending_input = store.pending_input(run.id)
    if pending_input:
        print(f"awaiting_input: task={pending_input['task_id']}")
        print(f"question: {pending_input['question']}")
        if pending_input["options"]:
            print(f"options: {', '.join(pending_input['options'])}")
    for task in store.list_tasks(run.id):
        print(
            f"task: {task.id} state={task.state.value} attempts={task.attempts}"
            + (f" error={task.last_error}" if task.last_error else "")
            + (f" depends_on={','.join(task.dependencies)}" if task.dependencies else "")
        )
    artifacts = store.list_artifacts(run.id)
    for artifact in artifacts:
        print(
            f"artifact: {artifact['path']} kind={artifact['kind']} size={artifact['size']} sha256={artifact['sha256']}"
        )
    return 0


def _status_payload(config: Config, run_id: str) -> dict[str, object] | None:
    store = Store(config.database)
    run = store.get_run(run_id)
    if run is None:
        return None
    tasks = store.list_tasks(run.id)
    current_plan = store.get_current_plan(run.id)
    events = store.list_events(run.id)
    latest_evaluations = {
        event["task_id"]: {
            "event_id": event["id"],
            "created_at": event["created_at"],
            **event["payload"],
        }
        for event in events
        if event["type"] == "task_evaluated" and event["task_id"] is not None
    }
    latest_agents = {
        event["task_id"]: {
            "event_id": event["id"],
            "created_at": event["created_at"],
            **event["payload"],
        }
        for event in events
        if event["type"] in {"agent_finished", "agent_failed"} and event["task_id"] is not None
    }
    latest_recovery = next(
        (
            event["payload"].get("proposal")
            for event in reversed(events)
            if event["type"] == "recovery_proposed"
            and isinstance(event["payload"].get("proposal"), dict)
        ),
        None,
    )
    algorithm_manifest = None
    if current_plan is not None and current_plan.algorithm_problem is not None:
        algorithm_manifest = next(
            (item for item in reversed(store.list_artifacts(run.id)) if item["kind"] == "algorithm_manifest"),
            None,
        )
    conversation_manifest = _conversation_manifest(run)
    evolution_finished = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_finished" and isinstance(event["payload"], dict)
        ),
        None,
    )
    evolution_configured = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_configured" and isinstance(event["payload"], dict)
        ),
        None,
    )
    evolution_iterations = (
        evolution_finished.get("iterations")
        if isinstance(evolution_finished, dict) and isinstance(evolution_finished.get("iterations"), int)
        else sum(1 for event in events if event["type"] == "evolution_iteration")
    )
    evolution_candidates = (
        evolution_finished.get("evaluated_candidates")
        if isinstance(evolution_finished, dict) and isinstance(evolution_finished.get("evaluated_candidates"), int)
        else sum(1 for event in events if event["type"] == "evolution_candidate_archived")
    )
    evolution_link = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_linked" and isinstance(event.get("payload"), dict)
        ),
        None,
    )
    linked_evolution = None
    if evolution_link is not None:
        child_id = evolution_link.get("evolution_run_id")
        if isinstance(child_id, str):
            child = store.get_run(child_id)
            if child is not None:
                child_events = store.list_events(child.id)
                child_result = next(
                    (
                        event["payload"]
                        for event in reversed(child_events)
                        if event["type"] == "evolution_finished"
                        and isinstance(event.get("payload"), dict)
                    ),
                    None,
                )
                linked_evolution = {
                    "run_id": child.id,
                    "status": child.status.value,
                    "workspace": str(child.workspace),
                    "strategy": evolution_link.get("strategy"),
                    "result": child_result,
                }
            else:
                linked_evolution = {"run_id": child_id, "status": "missing"}
    artifacts = store.list_artifacts(run.id)
    algorithm_outputs = [item for item in artifacts if item["kind"] == "output"]
    role_evidence = [item for item in artifacts if item["kind"] == "role_evidence"]
    return {
        "run": {
            "id": run.id,
            "goal": run.goal,
            "status": run.status.value,
            "workspace": str(run.workspace),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "runner_pid": run.runner_pid,
            "runner_pgid": run.runner_pgid,
            "current_plan_id": run.current_plan_id,
            "current_plan_version": run.current_plan_version,
            "route_domain": run.route_domain,
            "route_reason": run.route_reason,
            "route_confidence": run.route_confidence,
            "solver_profile": run.solver_profile,
            "evaluator_profile": run.evaluator_profile,
            "required_capabilities": list(run.route_required_capabilities),
            "route_evidence": list(run.route_evidence),
            "budget": (run.budget or BudgetSpec()).to_dict(),
        },
        "route": {
            "domain": run.route_domain,
            "reason": run.route_reason,
            "confidence": run.route_confidence,
            "solver_profile": run.solver_profile,
            "evaluator_profile": run.evaluator_profile,
            "required_capabilities": list(run.route_required_capabilities),
            "evidence": list(run.route_evidence),
        } if run.route_domain else None,
        "budget": (run.budget or BudgetSpec()).to_dict(),
        "tasks": [
            {
                "id": task.id,
                "plan_task_id": task.plan_task_id,
                "run_id": task.run_id,
                "title": task.title,
                "state": task.state.value,
                "attempts": task.attempts,
                "result_path": str(task.result_path) if task.result_path else None,
                "last_error": task.last_error,
                "dependencies": list(task.dependencies),
                "acceptance": task.acceptance,
                "evaluation": latest_evaluations.get(task.id),
                "agent": latest_agents.get(task.id),
            }
            for task in tasks
        ],
        "artifacts": artifacts,
        # Keep structured data discoverable without requiring callers to filter the complete
        # audit ledger.  The rows remain the same hashed, run-relative artifact metadata.
        "algorithm_outputs": algorithm_outputs,
        "role_evidence": role_evidence,
        "input_request": store.pending_input(run.id),
        "recovery": latest_recovery,
        "plan": current_plan.to_dict() if current_plan else None,
        "algorithm_problem": current_plan.algorithm_problem if current_plan else None,
        "algorithm_workspace": algorithm_manifest,
        "conversation": conversation_manifest,
        "evolution": {
            "configured": evolution_configured,
            "result": evolution_finished,
            "iterations": evolution_iterations,
            "candidates": evolution_candidates,
            "linked": linked_evolution,
        } if evolution_configured or evolution_finished or linked_evolution else None,
        "decisions": store.list_decisions(run.id),
        "agents": [
            {"task_id": task_id, **payload}
            for task_id, payload in latest_agents.items()
        ],
    }


def _print_events(config: Config, run_id: str) -> int:
    store = Store(config.database)
    if store.get_run(run_id) is None:
        print(f"unknown run: {run_id}", file=sys.stderr)
        return 2
    for event in store.list_events(run_id):
        task = f" task={event['task_id']}" if event["task_id"] else ""
        print(f"{event['created_at']} {event['type']}{task} {event['payload']}")
    return 0


def _emit(payload: object, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
        return
    print(payload)


def _emit_error(message: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)


def _parse_command(value: str | None, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        command = tuple(shlex.split(value))
    except ValueError as exc:
        raise ValueError(f"{label} is not valid shell-like argument text: {exc}") from exc
    if not command:
        raise ValueError(f"{label} must not be empty")
    return command


def _adapter_fingerprint(
    command: tuple[str, ...],
    *,
    kind: str,
    name: str,
    role: str,
    required_capabilities: tuple[str, ...] = (),
) -> str | None:
    """Return a credential-safe identity for one explicit evolution adapter."""
    if not command:
        return None
    payload = {
        "command": list(command),
        "kind": kind,
        "name": name,
        "required_capabilities": sorted(set(required_capabilities)),
        "role": role,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _portfolio_fingerprint(
    commands: tuple[tuple[str, ...], ...],
    *,
    kind: str = "portfolio-generator",
    name: str,
    role: str,
    required_capabilities: tuple[str, ...] = (),
) -> str | None:
    """Return a digest for an ordered portfolio without persisting raw command arguments."""
    if not commands:
        return None
    payload = {
        "commands": [list(command) for command in commands],
        "kind": kind,
        "name": name,
        "required_capabilities": sorted(set(required_capabilities)),
        "role": role,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _runtime_fingerprint(
    runtime_name: str,
    *,
    command: tuple[str, ...] = (),
    endpoint: str | None = None,
    model: str | None = None,
    name: str,
    role: str,
    required_capabilities: tuple[str, ...] = (),
    agent_loop: bool = False,
    loop_max_steps: int = 40,
    loop_allow_exec: bool = False,
    loop_memory: bool = False,
    loop_session_history: bool = False,
) -> str:
    """Return a credential-safe identity for one repository-owned runtime Agent."""
    payload = {
        "command": list(command),
        "endpoint": endpoint,
        "kind": "runtime",
        "model": model,
        "name": name,
        "required_capabilities": sorted(set(required_capabilities)),
        "role": role,
        "runtime": runtime_name,
    }
    if agent_loop:
        payload["agent_loop"] = {
            "allow_exec": loop_allow_exec,
            "max_steps": loop_max_steps,
            "memory": loop_memory,
            "session_history": loop_session_history,
        }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_evolution_runtime(
    config: Config,
    args: argparse.Namespace,
    runtime_name: str,
    command: tuple[str, ...],
    endpoint: str | None,
    model: str | None,
    api_key: str | None,
) -> object:
    """Construct one fresh repository runtime for an evolution role."""
    runtime = build_runtime(runtime_name, command or None, endpoint, model, api_key)
    if not args.agent_runtime_loop:
        return runtime
    if not isinstance(runtime, OpenAICompatibleRuntime):
        raise ValueError(  # noqa: TRY004 - this is a user-facing option conflict
            "--agent-runtime-loop requires --agent-runtime openai-compatible"
        )
    memory = MemoryStore(config.database) if args.agent_runtime_memory else None
    if memory is not None:
        memory.initialize()
    tools = LocalToolRegistry(
        allow_exec=args.agent_runtime_allow_exec,
        memory=memory,
        redactions=(runtime.api_key,) if runtime.api_key else (),
    )
    return AgentLoopRuntime(
        runtime,
        tools=tools,
        max_steps=args.agent_runtime_max_steps,
        memory=memory,
        session_history=args.agent_runtime_session_history,
    )


def _runner_fingerprint(command: tuple[str, ...], timeout: float) -> str | None:
    """Return a credential-safe identity for an explicit candidate runner."""
    if not command:
        return None
    payload = {
        "command": list(command),
        "kind": "candidate-runner",
        "timeout": timeout,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compiler_fingerprint(runtime: object) -> str:
    """Return a credential-safe identity for the solve contract compiler runtime."""
    payload = {
        "kind": "contract-compiler",
        "runtime": getattr(runtime, "name", type(runtime).__name__),
        "command": list(getattr(runtime, "command", ()) or ()),
        "endpoint": getattr(runtime, "endpoint", None),
        "model": getattr(runtime, "model", None),
        "mode": getattr(runtime, "name", "runtime"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _conversation_manifest(run: Run) -> dict[str, object] | None:
    path = Path(run.workspace) / "solve" / "compiler-manifest.json"
    try:
        path.resolve(strict=False).relative_to(Path(run.workspace).resolve())
    except ValueError:
        return None
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _conversation_plan_factory(
    args: argparse.Namespace, manifest: dict[str, object] | None = None
) -> object | None:
    """Resolve role-plan mode, preferring the persisted mode during answer/resume."""
    if getattr(args, "role_dag", False) or (
        manifest is not None and manifest.get("plan_kind") == "role_dag"
    ):
        return build_algorithm_role_plan
    return None


def _read_conversation_goal(args: argparse.Namespace) -> str:
    if args.goal == "-":
        goal = sys.stdin.read()
    elif isinstance(args.goal, str):
        goal = args.goal
    else:
        goal = ""
    if not goal.strip():
        raise ValueError("solve requires a goal or --run-id with --resume")
    if len(goal.encode("utf-8")) > 8_000:
        raise ValueError("solve goal exceeds 8 KiB")
    return goal.strip()


def _safe_input_destination(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("input destination must be non-empty")
    value = value.strip()
    if "\\" in value or "\x00" in value:
        raise ValueError("input destination must be a portable relative path")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("input destination must be a portable relative path")
    return "/".join(candidate.parts)


def _input_source_and_destination(raw: object) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("--input requires SOURCE or SOURCE=DEST")
    source_text, separator, destination = raw.partition("=")
    source = Path(source_text if separator else raw).expanduser()
    if not source_text.strip():
        raise ValueError("--input source must be non-empty")
    if source.is_symlink():
        raise ValueError(f"input source must not be a symlink: {source}")
    source_path = source.resolve(strict=False)
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError(f"input source is not a regular file: {source}")
    target = destination.strip() if separator else source_path.name
    return source_path, _safe_input_destination(target)


def _path_has_symlink(root: Path, path: Path) -> bool:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            return True
        if current == root:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _stage_input_files(
    run: Run, store: Store, raw_inputs: list[str] | tuple[str, ...] | None
) -> tuple[str, ...]:
    """Copy explicit user data into a run-relative, hashed ``data/raw`` directory.

    Staging is idempotent for the same path and bytes, which lets a parent Agent safely retry a
    detached ``solve`` invocation. A different file at an existing destination is rejected rather
    than silently changing the problem underneath an immutable run.
    """
    values = tuple(raw_inputs or ())
    if len(values) > MAX_INPUT_FILES:
        raise ValueError(f"at most {MAX_INPUT_FILES} input files may be staged")
    if not values:
        return ()
    root = Path(run.workspace).expanduser().resolve(strict=False)
    raw_root = root / "data" / "raw"
    if _path_has_symlink(root, raw_root):
        raise ValueError("run data/raw directory must not be a symlink")
    raw_root.mkdir(parents=True, exist_ok=True)
    tasks = store.list_tasks(run.id)
    if not tasks:
        raise ValueError("run has no task to own staged input artifacts")
    owner_task = tasks[0].id
    artifact_store = ArtifactStore(root, store, run.id)
    staged: list[str] = []
    for raw in values:
        source, destination = _input_source_and_destination(raw)
        size = source.stat().st_size
        if size > MAX_INPUT_FILE_BYTES:
            raise ValueError(
                f"input source exceeds {MAX_INPUT_FILE_BYTES} bytes: {source}"
            )
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        target = root / "data" / "raw" / destination
        if _path_has_symlink(root, target):
            raise ValueError(f"input destination is symlinked: {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f"input destination already contains different data: {destination}")
        else:
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(content)
            temporary.replace(target)
        relative = f"data/raw/{destination}"
        if not any(
            item["path"] == relative
            and item["kind"] == "input_data"
            and item["sha256"] == digest
            for item in store.list_artifacts(run.id)
        ):
            artifact_store.record(target, owner_task, kind="input_data")
        store.append_event(
            run.id,
            "algorithm_input_staged",
            {"path": relative, "size": size, "sha256": digest},
            task_id=owner_task,
            event_id=f"event-algorithm-input-{run.id}-{hashlib.sha256(relative.encode()).hexdigest()}",
        )
        staged.append(relative)
    return tuple(staged)


def _solve(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Compile and execute one conversational algorithm mission."""
    if not args.evolve and any(
        getattr(args, name, None) is not None
        for name in (
            "strategy",
            "openevolve_command",
            "max_rounds",
            "stagnation_rounds",
            "population_size",
            "offspring_per_iteration",
            "islands",
            "migration_interval",
            "migration_rate",
            "seed",
            "timeout",
        )
    ):
        raise ValueError("evolution options require --evolve")
    if args.evolve:
        _validate_evolution_cli_bounds(args)
    controller = _controller(args, config)
    runtime = controller.runtime
    fingerprint = _compiler_fingerprint(runtime)
    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        run = controller.store.get_run(args.run_id)
        if run is None:
            raise ValueError(f"unknown run: {args.run_id}")
        if args.workspace is not None and args.workspace.expanduser().resolve() != run.workspace:
            raise ValueError("--workspace does not match the existing conversational run")
        manifest = _conversation_manifest(run)
        if manifest is not None and manifest.get("runtime_fingerprint") not in {None, fingerprint}:
            raise ValueError("solve resume compiler runtime does not match the existing run")
        evolution_request = _latest_evolution_request(controller.store, run.id)
        if args.evolve and evolution_request is None:
            controller.store.append_event(
                run.id,
                "evolution_requested",
                _evolution_request_payload(args),
                event_id="event-evolution-request-" + hashlib.sha256(run.id.encode()).hexdigest(),
            )
            evolution_request = _evolution_request_payload(args)
        if args.evolve and evolution_request is not None:
            _validate_evolution_override(args, evolution_request)
        _stage_input_files(run, controller.store, args.input_files)
        settled = controller.resume_conversational(
            run.id,
            RuntimeContractCompiler(runtime),
            compiler_fingerprint=fingerprint,
            plan_factory=_conversation_plan_factory(args, manifest),
            execute_plan=not args.evolve and evolution_request is None,
        )
        effective_args = _evolution_args(args, evolution_request)
        if effective_args.evolve and settled.current_plan_id is not None:
            _solve_evolution(config, effective_args, controller, settled)
            settled = controller.store.get_run(settled.id) or settled
        return _solve_payload(controller, settled)
    goal = _read_conversation_goal(args)
    run = controller.create_conversational_run(
        goal, workspace=args.workspace, compiler_fingerprint=fingerprint
    )
    evolution_request = None
    if args.evolve:
        evolution_request = _evolution_request_payload(args)
        controller.store.append_event(
            run.id,
            "evolution_requested",
            evolution_request,
            event_id="event-evolution-request-" + hashlib.sha256(run.id.encode()).hexdigest(),
        )
    _stage_input_files(run, controller.store, args.input_files)
    if args.detach:
        return _detach_solve(config, args, run)
    settled = controller.resume_conversational(
        run.id,
        RuntimeContractCompiler(runtime),
        compiler_fingerprint=fingerprint,
        plan_factory=_conversation_plan_factory(args),
        execute_plan=not args.evolve,
    )
    effective_args = _evolution_args(args, evolution_request)
    if effective_args.evolve and settled.current_plan_id is not None:
        _solve_evolution(config, effective_args, controller, settled)
        settled = controller.store.get_run(settled.id) or settled
    return _solve_payload(controller, settled)


def _evolution_request_payload(args: argparse.Namespace) -> dict[str, object]:
    """Return only bounded, non-secret settings needed to continue a solve handoff."""
    return {
        "strategy": args.strategy,
        "max_rounds": args.max_rounds,
        "stagnation_rounds": args.stagnation_rounds,
        "population_size": args.population_size if args.population_size is not None else 8,
        "offspring_per_iteration": (
            args.offspring_per_iteration if args.offspring_per_iteration is not None else 1
        ),
        "islands": args.islands if args.islands is not None else 1,
        "migration_interval": (
            args.migration_interval if args.migration_interval is not None else 0
        ),
        "migration_rate": args.migration_rate if args.migration_rate is not None else 0.1,
        "seed": args.seed,
        "timeout": args.timeout if args.timeout is not None else 900.0,
        "openevolve_command_configured": bool(args.openevolve_command),
    }


def _validate_evolution_cli_bounds(args: argparse.Namespace) -> None:
    """Validate option bounds before a handoff request is persisted in the intake ledger."""
    try:
        EvolutionConfig(
            strategy="loop",
            max_rounds=args.max_rounds if args.max_rounds is not None else 1,
            stagnation_rounds=(
                args.stagnation_rounds if args.stagnation_rounds is not None else 1
            ),
            population_size=args.population_size if args.population_size is not None else 8,
            offspring_per_iteration=(
                args.offspring_per_iteration if args.offspring_per_iteration is not None else 1
            ),
            num_islands=args.islands if args.islands is not None else 1,
            migration_interval=(
                args.migration_interval if args.migration_interval is not None else 0
            ),
            migration_rate=args.migration_rate if args.migration_rate is not None else 0.1,
            rng_seed=args.seed,
            timeout_seconds=args.timeout if args.timeout is not None else 900.0,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid solve evolution options: {exc}") from exc


def _latest_evolution_request(store: Store, run_id: str) -> dict[str, object] | None:
    for event in reversed(store.list_events(run_id)):
        if event["type"] == "evolution_requested" and isinstance(event.get("payload"), dict):
            return event["payload"]
    return None


def _validate_evolution_override(args: argparse.Namespace, request: dict[str, object]) -> None:
    """Reject explicit resume settings that differ from the persisted handoff request."""
    for name in (
        "strategy",
        "max_rounds",
        "stagnation_rounds",
        "population_size",
        "offspring_per_iteration",
        "islands",
        "migration_interval",
        "migration_rate",
        "seed",
        "timeout",
    ):
        supplied = getattr(args, name, None)
        stored = request.get(name)
        if supplied is not None and stored is not None and supplied != stored:
            raise EvolutionError(f"solve evolution setting {name} does not match the existing handoff")


def _evolution_args(
    args: argparse.Namespace, request: dict[str, object] | None
) -> argparse.Namespace:
    """Overlay persisted handoff settings onto a CLI namespace during answer/resume."""
    if request is None:
        return args
    values = vars(args).copy()
    values["evolve"] = True
    for name in (
        "strategy",
        "openevolve_command",
        "max_rounds",
        "stagnation_rounds",
        "population_size",
        "offspring_per_iteration",
        "islands",
        "migration_interval",
        "migration_rate",
        "seed",
        "timeout",
    ):
        values.setdefault(name, None)
    for name in (
        "strategy",
        "max_rounds",
        "stagnation_rounds",
        "population_size",
        "offspring_per_iteration",
        "islands",
        "migration_interval",
        "migration_rate",
        "seed",
        "timeout",
    ):
        if name in request and request[name] is not None:
            values[name] = request[name]
    return argparse.Namespace(**values)


def _solve_evolution(
    config: Config, args: argparse.Namespace, controller: LocalController, parent: Run
) -> dict[str, object]:
    """Create or resume the evolution child linked to one compiled conversational run."""
    events = controller.store.list_events(parent.id)
    linked = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_linked" and isinstance(event.get("payload"), dict)
        ),
        None,
    )
    contract_payload = controller.store.get_current_plan(parent.id)
    if contract_payload is None or contract_payload.algorithm_problem is None:
        raise ValueError("solve --evolve requires a compiled algorithm contract")
    contract = AlgorithmProblemContract.from_dict(contract_payload.algorithm_problem)
    strategy_name = args.strategy or contract.evolution.strategy

    # Validate all strategy/runtime settings before creating any child workspace or mutating the
    # intake plan. This keeps malformed opt-in requests side-effect free.
    openevolve_command = _parse_command(args.openevolve_command, "--openevolve-command")
    max_rounds = args.max_rounds if args.max_rounds is not None else contract.evolution.max_rounds
    stagnation_rounds = (
        args.stagnation_rounds
        if args.stagnation_rounds is not None
        else contract.evolution.stagnation_rounds
    )
    if strategy_name == "openevolve":
        if not openevolve_command:
            raise ValueError("--evolve --strategy openevolve requires --openevolve-command")
        executable = Path(openevolve_command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("--openevolve-command must start with an existing absolute executable path")

        def generator(request):
            del request
            raise EvolutionError("openevolve does not use a native generator")

        def evaluator(path, candidate_contract):
            del path, candidate_contract
            raise EvolutionError("OpenEvolve result must include evaluation")

        generator_fingerprint = None
        evaluator_fingerprint = None
    else:
        if openevolve_command:
            raise ValueError("--openevolve-command requires --evolve --strategy openevolve")
        runtime = controller.runtime
        solver_adapter = RuntimeAgentAdapter(
            runtime,
            name="solve-evolution-solver",
            roles=("solver",),
            capabilities=DEFAULT_RUNTIME_CAPABILITIES,
        )
        evaluator_adapter = RuntimeAgentAdapter(
            runtime,
            name="solve-evolution-evaluator",
            roles=("evaluator",),
            capabilities=DEFAULT_RUNTIME_CAPABILITIES,
        )
        generator = AgentCandidateGenerator(
            solver_adapter, contract=contract, role="solver", timeout=args.timeout
        )
        evaluator = AgentCandidateEvaluator(
            evaluator_adapter, role="evaluator", timeout=args.timeout
        )
        runtime_fingerprint = _compiler_fingerprint(runtime)
        generator_fingerprint = hashlib.sha256(
            f"{runtime_fingerprint}:solver".encode()
        ).hexdigest()
        evaluator_fingerprint = hashlib.sha256(
            f"{runtime_fingerprint}:evaluator".encode()
        ).hexdigest()
    evolution_config = EvolutionConfig(
        strategy=strategy_name,
        max_rounds=max_rounds,
        stagnation_rounds=stagnation_rounds,
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        command=openevolve_command,
        generator_fingerprint=generator_fingerprint,
        evaluator_fingerprint=evaluator_fingerprint,
    )
    if linked is not None:
        linked_contract = linked.get("contract_sha256")
        if not isinstance(linked_contract, str) or linked_contract != contract.digest():
            raise EvolutionError("evolution link has an invalid contract digest")
        child_id = linked.get("evolution_run_id")
        if not isinstance(child_id, str) or not child_id:
            raise EvolutionError("evolution link has an invalid child run ID")
        child = controller.store.get_run(child_id)
        if child is None:
            raise EvolutionError("linked evolution run no longer exists")
        if linked.get("strategy") != strategy_name:
            raise EvolutionError("solve evolution strategy does not match the existing handoff")
        state_path = child.workspace / "evolution" / "state.json"
        if state_path.is_file():
            try:
                state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvolutionError("linked evolution state is not valid JSON") from exc
            if (
                isinstance(state_payload, dict)
                and state_payload.get("config") is not None
                and state_payload.get("config") != evolution_config.to_dict()
            ):
                raise EvolutionError("solve evolution settings do not match the existing handoff")
        if child.status.value not in {"succeeded", "failed", "cancelled"}:
            controller.run_evolution(
                child.id,
                contract,
                generator,
                evaluator,
                evolution_config,
                resume=True,
            )
            child = controller.store.get_run(child.id) or child
        return {"run": parent, "child": child}

    child_workspace = (Path(parent.workspace) / "evolution-run").resolve()
    existing = controller.store.get_run_by_workspace(child_workspace)
    if existing is not None:
        child = existing
        canonical_path = child.workspace / "evolution" / "contract.json"
        try:
            canonical = AlgorithmProblemContract.from_dict(
                json.loads(canonical_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("existing evolution handoff workspace has an invalid contract") from exc
        if canonical.digest() != contract.digest():
            raise EvolutionError("existing evolution handoff workspace belongs to another contract")
    else:
        child = controller.create_evolution_run(contract, workspace=child_workspace)
    # Re-run the copy after a crash between child creation and linking; identical bytes are
    # idempotent and conflicting bytes fail closed before strategy execution.
    controller.copy_staged_inputs(parent.id, child.id)
    controller.store.supersede_pending_tasks(parent.id, "replaced by explicit evolution handoff")
    controller.store.settle_run(parent.id)
    controller.store.append_event(
        parent.id,
        "evolution_linked",
        {
            "evolution_run_id": child.id,
            "contract_sha256": contract.digest(),
            "strategy": strategy_name,
        },
        event_id="event-evolution-link-" + hashlib.sha256(child.id.encode()).hexdigest(),
    )
    controller.store.append_event(
        child.id,
        "evolution_parent_linked",
        {"parent_run_id": parent.id, "contract_sha256": contract.digest()},
        event_id="event-evolution-parent-link-" + hashlib.sha256(parent.id.encode()).hexdigest(),
    )

    controller.run_evolution(
        child.id,
        contract,
        generator,
        evaluator,
        evolution_config,
    )
    return {"run": parent, "child": controller.store.get_run(child.id) or child}


def _solve_payload(controller: LocalController, run: Run) -> dict[str, object]:
    manifest = _conversation_manifest(run)
    input_data = [
        item for item in controller.store.list_artifacts(run.id) if item["kind"] == "input_data"
    ]
    algorithm_outputs = [
        item for item in controller.store.list_artifacts(run.id) if item["kind"] == "output"
    ]
    evolution_payload: dict[str, object] | None = None
    for event in reversed(controller.store.list_events(run.id)):
        if event["type"] != "evolution_linked" or not isinstance(event.get("payload"), dict):
            continue
        link = event["payload"]
        child_id = link.get("evolution_run_id")
        if not isinstance(child_id, str):
            break
        child = controller.store.get_run(child_id)
        if child is None:
            evolution_payload = {"run_id": child_id, "status": "missing"}
            break
        child_events = controller.store.list_events(child.id)
        result = next(
            (
                item["payload"]
                for item in reversed(child_events)
                if item["type"] == "evolution_finished" and isinstance(item.get("payload"), dict)
            ),
            None,
        )
        evolution_payload = {
            "run_id": child.id,
            "status": child.status.value,
            "workspace": str(child.workspace),
            "strategy": link.get("strategy"),
            "result": result,
        }
        break
    payload = {
        "run_id": run.id,
        "status": run.status.value,
        "run_status": run.status.value,
        "workspace": str(run.workspace),
        "input_request": controller.store.pending_input(run.id),
        "input_data": input_data,
        "algorithm_outputs": algorithm_outputs,
        "compiler": manifest,
        "plan": (
            {"plan_id": run.current_plan_id, "version": run.current_plan_version}
            if run.current_plan_id
            else None
        ),
    }
    if evolution_payload is not None:
        payload["evolution"] = evolution_payload
    return payload


def _detach_solve(config: Config, args: argparse.Namespace, run: Run) -> dict[str, object]:
    """Spawn a child that resumes a conversational mission with identical runtime settings."""
    log_path = run.workspace / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "famou",
        "solve",
        "--resume",
        "--run-id",
        run.id,
        "--runtime",
        args.runtime,
        "--home",
        str(config.home),
        "--json",
    ]
    if args.workspace:
        command.extend(("--workspace", str(args.workspace)))
    if args.role_dag:
        command.append("--role-dag")
    if args.evolve:
        command.append("--evolve")
    for option, value in (
        ("--strategy", args.strategy),
        ("--openevolve-command", args.openevolve_command),
        ("--max-rounds", args.max_rounds),
        ("--stagnation-rounds", args.stagnation_rounds),
        ("--population-size", args.population_size),
        ("--offspring-per-iteration", args.offspring_per_iteration),
        ("--islands", args.islands),
        ("--migration-interval", args.migration_interval),
        ("--migration-rate", args.migration_rate),
        ("--seed", args.seed),
        ("--timeout", args.timeout),
    ):
        if value is not None:
            command.extend((option, str(value)))
    if args.runtime_command:
        command.extend(("--command", args.runtime_command))
    if args.endpoint:
        command.extend(("--endpoint", args.endpoint))
    if args.model:
        command.extend(("--model", args.model))
    if args.agent_loop:
        command.append("--agent-loop")
        command.extend(("--max-steps", str(args.max_steps)))
    if args.allow_exec:
        command.append("--allow-exec")
    if args.memory:
        command.append("--memory")
    if args.session_history:
        command.append("--session-history")
    child_env = None
    if args.api_key is not None:
        child_env = os.environ.copy()
        child_env["FAMOU_API_KEY"] = args.api_key
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=child_env,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            store = Store(config.database)
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            store.set_runner_process(run.id, pid, pgid)
            latest = store.get_run(run.id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                store.clear_runner_process(run.id)
    except OSError as exc:
        Store(config.database).cancel_run(run.id)
        raise ValueError(f"could not start detached solve: {exc}") from exc
    input_data = [
        item for item in Store(config.database).list_artifacts(run.id)
        if item["kind"] == "input_data"
    ]
    return {
        "run_id": run.id,
        "status": "pending",
        "run_status": "pending",
        "workspace": str(run.workspace),
        "detached": True,
        "input_data": input_data,
    }


def _evolve(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Create/execute one ledger-backed local evolution run."""
    try:
        payload = json.loads(args.contract.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read contract {args.contract}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract is not valid JSON: {exc.msg}") from exc
    contract = AlgorithmProblemContract.from_dict(payload)
    if args.strategy and args.strategy != contract.evolution.strategy:
        contract = replace(contract, evolution=replace(contract.evolution, strategy=args.strategy))
    controller = LocalController(config, build_runtime("mock", None, None, None, None))
    existing_run = None
    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        existing_run = controller.store.get_run(args.run_id)
        if existing_run is None:
            raise ValueError(f"unknown run: {args.run_id}")
        if args.workspace is not None and args.workspace.expanduser().resolve() != existing_run.workspace:
            raise ValueError("--workspace does not match the existing evolution run")
        canonical_path = existing_run.workspace / "evolution" / "contract.json"
        try:
            canonical = AlgorithmProblemContract.from_dict(
                json.loads(canonical_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("existing evolution run has an invalid canonical contract") from exc
        if canonical.digest() != contract.digest():
            raise ValueError("supplied contract does not match the existing evolution run")
        contract = canonical
    strategy_name = args.strategy or contract.evolution.strategy
    workspace = (existing_run.workspace if existing_run is not None else args.workspace)
    if workspace is None:
        if args.resume:
            raise ValueError("--resume requires an existing run")
        workspace = config.runs / f"evolution-{uuid.uuid4().hex[:12]}"
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    max_rounds = args.max_rounds if args.max_rounds is not None else contract.evolution.max_rounds
    stagnation_rounds = args.stagnation_rounds if args.stagnation_rounds is not None else contract.evolution.stagnation_rounds
    openevolve_command = _parse_command(args.openevolve_command, "--openevolve-command")
    agent_command = _parse_command(args.agent_command, "--agent-command")
    agent_portfolio_commands = tuple(
        _parse_command(value, "--agent-portfolio-command")
        for value in args.agent_portfolio_commands
    )
    evaluator_agent_command = _parse_command(
        args.evaluator_agent_command, "--evaluator-agent-command"
    )
    evaluator_portfolio_commands = tuple(
        _parse_command(value, "--evaluator-portfolio-command")
        for value in args.evaluator_portfolio_commands
    )
    candidate_runner_command = _parse_command(
        args.candidate_runner_command, "--candidate-runner-command"
    )
    agent_runtime = args.agent_runtime
    agent_runtime_command = _parse_command(
        args.agent_runtime_command, "--agent-runtime-command"
    )
    runtime_profile_options = (
        agent_runtime_command,
        args.agent_runtime_endpoint,
        args.agent_runtime_model,
        args.agent_runtime_api_key,
    )
    if (
        not isinstance(args.agent_runtime_max_steps, int)
        or isinstance(args.agent_runtime_max_steps, bool)
        or not 1 <= args.agent_runtime_max_steps <= 200
    ):
        raise ValueError("--agent-runtime-max-steps must be between 1 and 200")
    loop_options_used = bool(
        args.agent_runtime_loop
        or args.agent_runtime_allow_exec
        or args.agent_runtime_memory
        or args.agent_runtime_session_history
        or args.agent_runtime_max_steps != 40
    )
    if loop_options_used and agent_runtime is None:
        raise ValueError("evolution runtime loop options require --agent-runtime")
    if args.agent_runtime_loop and agent_runtime != "openai-compatible":
        raise ValueError("--agent-runtime-loop requires --agent-runtime openai-compatible")
    if any(
        option
        for option in (
            args.agent_runtime_allow_exec,
            args.agent_runtime_memory,
            args.agent_runtime_session_history,
        )
    ) and not args.agent_runtime_loop:
        raise ValueError("evolution loop options require --agent-runtime-loop")
    if args.agent_runtime_max_steps != 40 and not args.agent_runtime_loop:
        raise ValueError("--agent-runtime-max-steps requires --agent-runtime-loop")
    if agent_runtime is None and any(value is not None and value != () for value in runtime_profile_options):
        raise ValueError("runtime profile options require --agent-runtime")
    if agent_runtime == "subprocess" and not agent_runtime_command:
        raise ValueError("--agent-runtime subprocess requires --agent-runtime-command")
    if agent_runtime == "subprocess" and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    if agent_runtime == "openai-compatible" and agent_runtime_command:
        raise ValueError("--agent-runtime-command requires --agent-runtime subprocess")
    if agent_runtime in {"mock", None} and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    runtime_endpoint = args.agent_runtime_endpoint
    runtime_model = args.agent_runtime_model
    runtime_api_key = args.agent_runtime_api_key
    if agent_runtime == "openai-compatible":
        runtime_endpoint = runtime_endpoint or os.environ.get("FAMOU_MODEL_ENDPOINT")
        runtime_model = runtime_model or os.environ.get("FAMOU_MODEL") or "local"
        if runtime_api_key is None:
            runtime_api_key = os.environ.get("FAMOU_AGENT_RUNTIME_API_KEY")
    if agent_runtime != "openai-compatible" and args.agent_runtime_api_key is not None:
        raise ValueError("--agent-runtime-api-key requires --agent-runtime openai-compatible")
    generator_fingerprint: str | None = None
    evaluator_fingerprint: str | None = None
    runner_fingerprint: str | None = _runner_fingerprint(candidate_runner_command, args.timeout)
    if strategy_name == "openevolve":
        if (
            agent_command
            or agent_portfolio_commands
            or evaluator_agent_command
            or evaluator_portfolio_commands
            or agent_runtime
            or any(value is not None and value != () for value in runtime_profile_options)
            or candidate_runner_command
        ):
            raise ValueError(
                "native solver/evaluator and candidate runner commands are only supported by loop and population"
            )
        command = openevolve_command
        if not command:
            raise ValueError("openevolve strategy requires --openevolve-command")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("--openevolve-command must start with an existing absolute executable path")
        evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
        if evaluator_command:
            evaluator_fingerprint = _adapter_fingerprint(
                evaluator_command,
                kind="evaluator",
                name="command-evaluator",
                role="evaluator",
            )
            evaluator = CommandCandidateEvaluator(evaluator_command, args.timeout)
        else:
            def evaluator(path, contract):
                del path, contract
                raise EvolutionError("OpenEvolve result must include evaluation or --evaluator-command")

        def generator(request):
            del request
            raise EvolutionError("openevolve does not use a native generator")
    else:
        generator_command = _parse_command(args.generator_command, "--generator-command")
        evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
        if generator_command and (agent_command or agent_portfolio_commands):
            raise ValueError("generator and Agent portfolio commands are mutually exclusive")
        if agent_command and agent_portfolio_commands:
            raise ValueError("--agent-command and --agent-portfolio-command are mutually exclusive")
        solver_explicit = bool(generator_command or agent_command or agent_portfolio_commands)
        evaluator_explicit = bool(
            evaluator_command or evaluator_agent_command or evaluator_portfolio_commands
        )
        if candidate_runner_command and not evaluator_command:
            raise ValueError("--candidate-runner-command requires --evaluator-command")
        if agent_runtime and solver_explicit and evaluator_explicit:
            raise ValueError(
                "--agent-runtime is unused when both solver and evaluator are explicitly configured"
            )
        if sum(
            bool(option)
            for option in (evaluator_command, evaluator_agent_command, evaluator_portfolio_commands)
        ) > 1:
            raise ValueError(
                "--evaluator-command, --evaluator-agent-command, and "
                "--evaluator-portfolio-command are mutually exclusive"
            )
        if not evaluator_explicit and not agent_runtime:
            raise ValueError(
                "loop and population require --evaluator-command or "
                "--evaluator-agent-command or --evaluator-portfolio-command plus "
                "--generator-command, --agent-command, or "
                "at least two --agent-portfolio-command options"
            )
        if agent_portfolio_commands and len(agent_portfolio_commands) < 2:
            raise ValueError("--agent-portfolio-command requires at least two commands")
        if evaluator_portfolio_commands and len(evaluator_portfolio_commands) < 2:
            raise ValueError("--evaluator-portfolio-command requires at least two commands")
        if agent_command:
            generator_fingerprint = _adapter_fingerprint(
                agent_command,
                kind="generator",
                name=args.agent_name,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
            )
        elif agent_portfolio_commands:
            generator_fingerprint = _portfolio_fingerprint(
                agent_portfolio_commands,
                name=args.agent_name,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
            )
        elif agent_runtime:
            generator_fingerprint = _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name=args.agent_name,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        else:
            generator_fingerprint = _adapter_fingerprint(
                generator_command,
                kind="generator",
                name="command-generator",
                role="generator",
            )
        if evaluator_agent_command:
            evaluator_fingerprint = _adapter_fingerprint(
                evaluator_agent_command,
                kind="evaluator",
                name=args.evaluator_agent_name,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
            )
        elif evaluator_portfolio_commands:
            evaluator_fingerprint = _portfolio_fingerprint(
                evaluator_portfolio_commands,
                kind="portfolio-evaluator",
                name=args.evaluator_agent_name,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
            )
        elif agent_runtime:
            evaluator_fingerprint = _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name=args.evaluator_agent_name,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        else:
            evaluator_fingerprint = _adapter_fingerprint(
                evaluator_command,
                kind="evaluator",
                name="command-evaluator",
                role="evaluator",
            )
        if agent_command:
            declared = {*DEFAULT_RUNTIME_CAPABILITIES, *args.agent_capabilities}
            adapter = CommandAgentAdapter(
                agent_command,
                roles=(args.agent_role,),
                capabilities=tuple(sorted(declared)),
                name=args.agent_name,
            )
            generator = AgentCandidateGenerator(
                adapter,
                contract=contract,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                timeout=args.timeout,
            )
        elif agent_portfolio_commands:
            declared = {*DEFAULT_RUNTIME_CAPABILITIES, *args.agent_capabilities}
            adapters = tuple(
                CommandAgentAdapter(
                    command,
                    roles=(args.agent_role,),
                    capabilities=tuple(sorted(declared)),
                    name=f"{args.agent_name}-{index:02d}",
                )
                for index, command in enumerate(agent_portfolio_commands, start=1)
            )
            generator = AgentPortfolioGenerator(
                adapters,
                contract=contract,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                timeout=args.timeout,
            )
        elif agent_runtime:
            runtime = _build_evolution_runtime(
                config,
                args,
                agent_runtime,
                agent_runtime_command,
                runtime_endpoint,
                runtime_model,
                runtime_api_key,
            )
            generator_adapter = RuntimeAgentAdapter(
                runtime,
                name=args.agent_name,
                roles=(args.agent_role,),
                capabilities=tuple(sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(args.agent_capabilities))),
            )
            generator = AgentCandidateGenerator(
                generator_adapter,
                contract=contract,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                timeout=args.timeout,
            )
        elif generator_command:
            generator = CommandCandidateGenerator(generator_command, args.timeout)
        else:
            raise ValueError("loop and population require --generator-command or --agent-command")
        if evaluator_agent_command:
            evaluator_adapter = CommandAgentAdapter(
                evaluator_agent_command,
                roles=(args.evaluator_agent_role,),
                capabilities=tuple(
                    sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(args.evaluator_agent_capabilities))
                ),
                name=args.evaluator_agent_name,
            )
            evaluator = AgentCandidateEvaluator(
                evaluator_adapter,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                timeout=args.timeout,
            )
        elif evaluator_portfolio_commands:
            evaluator_adapters = tuple(
                CommandAgentAdapter(
                    command,
                    roles=(args.evaluator_agent_role,),
                    capabilities=tuple(
                        sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(args.evaluator_agent_capabilities))
                    ),
                    name=f"{args.evaluator_agent_name}-{index:02d}",
                )
                for index, command in enumerate(evaluator_portfolio_commands, start=1)
            )
            evaluator = AgentEvaluatorEnsemble(
                evaluator_adapters,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                timeout=args.timeout,
            )
        elif agent_runtime:
            runtime = _build_evolution_runtime(
                config,
                args,
                agent_runtime,
                agent_runtime_command,
                runtime_endpoint,
                runtime_model,
                runtime_api_key,
            )
            evaluator_adapter = RuntimeAgentAdapter(
                runtime,
                name=args.evaluator_agent_name,
                roles=(args.evaluator_agent_role,),
                capabilities=tuple(
                    sorted(
                        set(DEFAULT_RUNTIME_CAPABILITIES)
                        | set(args.evaluator_agent_capabilities)
                    )
                ),
            )
            evaluator = AgentCandidateEvaluator(
                evaluator_adapter,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                timeout=args.timeout,
            )
        else:
            evaluator = CommandCandidateEvaluator(evaluator_command, args.timeout)
        if candidate_runner_command:
            evaluator = ExecutionAwareCandidateEvaluator(
                CommandCandidateRunner(candidate_runner_command, args.timeout), evaluator
            )
        command = agent_command
    evolution_config = EvolutionConfig(
        strategy=strategy_name,
        max_rounds=max_rounds,
        stagnation_rounds=stagnation_rounds,
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        command=command,
        generator_fingerprint=generator_fingerprint,
        evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint,
    )
    if args.resume:
        state_path = workspace / "evolution" / "state.json"
        if state_path.is_file():
            try:
                state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("existing evolution state is not valid JSON") from exc
            if (
                isinstance(state_payload, dict)
                and state_payload.get("config") is not None
                and state_payload.get("config") != evolution_config.to_dict()
            ):
                raise ValueError("evolution resume configuration does not match the existing run")
    if existing_run is None:
        run = controller.create_evolution_run(contract, workspace=workspace)
    else:
        run = existing_run
    if args.detach and not args.resume:
        return _detach_evolution(config, args, run, contract)
    settled, result = controller.run_evolution(
        run.id,
        contract,
        generator,
        evaluator,
        evolution_config,
        resume=args.resume,
    )
    return {
        **result.to_dict(),
        "run_id": run.id,
        "status": result.status,
        "run_status": settled.status.value,
        "workspace": str(settled.workspace),
        "contract_sha256": contract.digest(),
    }


def _benchmark(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Compare strategies with explicit commands or repository-owned runtime profiles."""
    try:
        payload = json.loads(args.contract.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read contract {args.contract}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract is not valid JSON: {exc.msg}") from exc
    contract = AlgorithmProblemContract.from_dict(payload)
    strategies = tuple(args.strategies or ("loop", "population"))
    generator_command = _parse_command(args.generator_command, "--generator-command")
    evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
    openevolve_command = _parse_command(args.openevolve_command, "--openevolve-command")
    agent_runtime = args.agent_runtime
    agent_runtime_command = _parse_command(
        args.agent_runtime_command, "--agent-runtime-command"
    )
    runtime_profile_options = (
        agent_runtime_command,
        args.agent_runtime_endpoint,
        args.agent_runtime_model,
        args.agent_runtime_api_key,
    )
    if (
        not isinstance(args.agent_runtime_max_steps, int)
        or isinstance(args.agent_runtime_max_steps, bool)
        or not 1 <= args.agent_runtime_max_steps <= 200
    ):
        raise ValueError("--agent-runtime-max-steps must be between 1 and 200")
    loop_options_used = bool(
        args.agent_runtime_loop
        or args.agent_runtime_allow_exec
        or args.agent_runtime_memory
        or args.agent_runtime_session_history
        or args.agent_runtime_max_steps != 40
    )
    if loop_options_used and agent_runtime is None:
        raise ValueError("benchmark runtime loop options require --agent-runtime")
    if args.agent_runtime_loop and agent_runtime != "openai-compatible":
        raise ValueError("--agent-runtime-loop requires --agent-runtime openai-compatible")
    if any(
        option
        for option in (
            args.agent_runtime_allow_exec,
            args.agent_runtime_memory,
            args.agent_runtime_session_history,
        )
    ) and not args.agent_runtime_loop:
        raise ValueError("benchmark runtime loop options require --agent-runtime-loop")
    if args.agent_runtime_max_steps != 40 and not args.agent_runtime_loop:
        raise ValueError("--agent-runtime-max-steps requires --agent-runtime-loop")
    if agent_runtime is None and any(
        value is not None and value != () for value in runtime_profile_options
    ):
        raise ValueError("runtime profile options require --agent-runtime")
    if agent_runtime == "subprocess" and not agent_runtime_command:
        raise ValueError("--agent-runtime subprocess requires --agent-runtime-command")
    if agent_runtime == "subprocess" and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    if agent_runtime == "openai-compatible" and agent_runtime_command:
        raise ValueError("--agent-runtime-command requires --agent-runtime subprocess")
    if agent_runtime in {"mock", None} and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    if agent_runtime != "openai-compatible" and args.agent_runtime_api_key is not None:
        raise ValueError("--agent-runtime-api-key requires --agent-runtime openai-compatible")
    runtime_endpoint = args.agent_runtime_endpoint
    runtime_model = args.agent_runtime_model
    runtime_api_key = args.agent_runtime_api_key
    if agent_runtime == "openai-compatible":
        runtime_endpoint = runtime_endpoint or os.environ.get("FAMOU_MODEL_ENDPOINT")
        runtime_model = runtime_model or os.environ.get("FAMOU_MODEL") or "local"
        if runtime_api_key is None:
            runtime_api_key = os.environ.get("FAMOU_AGENT_RUNTIME_API_KEY")
        if not runtime_endpoint:
            raise ValueError(
                "openai-compatible runtime requires --agent-runtime-endpoint or FAMOU_MODEL_ENDPOINT"
            )
    if agent_runtime and "openevolve" in strategies:
        raise ValueError("--agent-runtime cannot be combined with --strategy openevolve")
    if "openevolve" in strategies and not openevolve_command:
        raise ValueError("benchmark requires --openevolve-command for openevolve")
    if openevolve_command and "openevolve" not in strategies:
        raise ValueError("--openevolve-command requires --strategy openevolve")
    native_selected = any(strategy != "openevolve" for strategy in strategies)
    if native_selected and not agent_runtime and not generator_command:
        raise ValueError("benchmark requires --generator-command for loop/population")
    if not evaluator_command and not agent_runtime:
        raise ValueError("benchmark requires --evaluator-command or --agent-runtime")
    if agent_runtime and generator_command and evaluator_command:
        raise ValueError("runtime profile is unused when generator and evaluator are explicit")
    max_rounds = args.max_rounds if args.max_rounds is not None else contract.evolution.max_rounds
    stagnation_rounds = (
        args.stagnation_rounds
        if args.stagnation_rounds is not None
        else contract.evolution.stagnation_rounds
    )
    benchmark_config = BenchmarkConfig(
        strategies=strategies,
        max_rounds=max_rounds,
        stagnation_rounds=stagnation_rounds,
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        generator_fingerprint=(
            _adapter_fingerprint(
                generator_command,
                kind="benchmark-generator",
                name="command-generator",
                role="solver",
            )
            if generator_command
            else _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name="benchmark-solver",
                role="solver",
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        ),
        evaluator_fingerprint=(
            _adapter_fingerprint(
                evaluator_command,
                kind="benchmark-evaluator",
                name="command-evaluator",
                role="evaluator",
            )
            if evaluator_command
            else _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name="benchmark-evaluator",
                role="evaluator",
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        ),
        strategy_commands={"openevolve": openevolve_command} if openevolve_command else {},
        runtime_profile=(
            {
                "kind": agent_runtime,
                "loop": args.agent_runtime_loop,
                "max_steps": args.agent_runtime_max_steps,
                "allow_exec": args.agent_runtime_allow_exec,
                "memory": args.agent_runtime_memory,
                "session_history": args.agent_runtime_session_history,
            }
            if agent_runtime
            else None
        ),
    )
    workspace = args.workspace
    if workspace is None:
        workspace = config.runs / f"benchmark-{uuid.uuid4().hex[:12]}"
    workspace = workspace.expanduser().resolve()

    def generator_factory(_strategy: str) -> CommandCandidateGenerator:
        if generator_command:
            return CommandCandidateGenerator(generator_command, args.timeout)
        runtime = _build_evolution_runtime(
            config,
            args,
            agent_runtime,
            agent_runtime_command,
            runtime_endpoint,
            runtime_model,
            runtime_api_key,
        )
        adapter = RuntimeAgentAdapter(runtime, name="benchmark-solver", roles=("solver",))
        return AgentCandidateGenerator(adapter, contract=contract, timeout=args.timeout)

    def evaluator_factory(_strategy: str) -> object:
        if evaluator_command:
            return CommandCandidateEvaluator(evaluator_command, args.timeout)
        runtime = _build_evolution_runtime(
            config,
            args,
            agent_runtime,
            agent_runtime_command,
            runtime_endpoint,
            runtime_model,
            runtime_api_key,
        )
        adapter = RuntimeAgentAdapter(runtime, name="benchmark-evaluator", roles=("evaluator",))
        return AgentCandidateEvaluator(adapter, timeout=args.timeout)

    report = BenchmarkRunner(
        contract,
        workspace,
        generator_factory=generator_factory,
        evaluator_factory=evaluator_factory,
        config=benchmark_config,
    ).run()
    status = (
        "completed"
        if any(item.status in {"completed", "stagnated"} for item in report.runs)
        else "failed"
    )
    return {**report.to_dict(), "status": status, "workspace": str(workspace)}


def _delegate(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Delegate one task through an explicitly supplied command adapter."""
    command = _parse_command(args.agent_command, "--agent-command")
    # The command adapter is the worker; the mock runtime is retained only to satisfy the
    # controller's backwards-compatible Runtime constructor and is never invoked here.
    controller = LocalController(
        config,
        build_runtime("mock", None, None, None, None),
    )
    if args.run_id:
        run = controller.store.get_run(args.run_id)
        if run is None:
            raise ValueError(f"unknown run: {args.run_id}")
        if args.prompt is not None and not args.prompt.strip():
            raise ValueError("prompt must not be empty")
    else:
        if not isinstance(args.prompt, str) or not args.prompt.strip():
            raise ValueError("delegate requires a prompt unless --run-id is supplied")
        run = controller.create(args.prompt.strip())
    if args.detach:
        if args.run_id:
            raise ValueError("--detach is only valid when creating a new delegated run")
        return _detach_delegate(config, args, run)
    declared_capabilities = set(args.capabilities) | set(run.route_required_capabilities)
    adapter = CommandAgentAdapter(
        command,
        roles=(args.agent_role,),
        capabilities=tuple(sorted(declared_capabilities)),
        name=args.agent_name,
    )
    controller.agent_registry = AgentRegistry([adapter])
    try:
        settled, result = controller.run_agent(
            run.id,
            role=args.agent_role,
            prompt=args.prompt.strip() if isinstance(args.prompt, str) and args.prompt.strip() else None,
            required_capabilities=tuple(args.capabilities),
            preferred_adapter=args.preferred_agent,
            task_id=args.task_id,
            timeout=args.timeout,
        )
    finally:
        controller.store.clear_runner_process(run.id, os.getpid())
    return {
        "run_id": settled.id,
        "task_id": args.task_id or controller.store.list_tasks(settled.id)[0].id,
        "status": result.status,
        "run_status": settled.status.value,
        "adapter": result.adapter_name,
        "role": result.role,
        "text": result.text,
        "artifacts": list(result.artifacts),
        "metadata": result.metadata,
        "error": result.error,
        "workspace": str(settled.workspace),
    }


def _detach_delegate(config: Config, args: argparse.Namespace, run: Run) -> dict[str, object]:
    """Spawn a child that re-enters the same explicit delegation request."""
    log_path = run.workspace / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "famou",
        "delegate",
        "--run-id",
        run.id,
        "--agent-command",
        args.agent_command,
        "--agent-name",
        args.agent_name,
        "--agent-role",
        args.agent_role,
        "--home",
        str(config.home),
        "--json",
    ]
    for capability in args.capabilities:
        command.extend(("--capability", capability))
    if args.preferred_agent:
        command.extend(("--preferred-agent", args.preferred_agent))
    if args.timeout is not None:
        command.extend(("--timeout", str(args.timeout)))
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            store = Store(config.database)
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            store.set_runner_process(run.id, pid, pgid)
            latest = store.get_run(run.id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                store.clear_runner_process(run.id)
    except OSError as exc:
        Store(config.database).cancel_run(run.id)
        raise AgentError(f"could not start detached delegation: {exc}") from exc
    return {
        "run_id": run.id,
        "status": "pending",
        "run_status": "pending",
        "workspace": str(run.workspace),
        "detached": True,
    }


def _detach_evolution(
    config: Config,
    args: argparse.Namespace,
    run: Run,
    contract: AlgorithmProblemContract,
) -> dict[str, object]:
    """Spawn a child process that resumes the already-created local evolution run."""
    run_id = run.id
    workspace = run.workspace
    log_path = workspace / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "famou",
        "evolve",
        str(args.contract.expanduser().resolve()),
        "--resume",
        "--run-id",
        run_id,
        "--home",
        str(config.home),
        "--json",
    ]
    if args.strategy:
        command.extend(("--strategy", args.strategy))
    if args.generator_command:
        command.extend(("--generator-command", args.generator_command))
    if args.agent_command:
        command.extend(("--agent-command", args.agent_command))
    for portfolio_command in args.agent_portfolio_commands:
        command.extend(("--agent-portfolio-command", portfolio_command))
    if args.agent_runtime:
        command.extend(("--agent-runtime", args.agent_runtime))
    if args.agent_runtime_command:
        command.extend(("--agent-runtime-command", args.agent_runtime_command))
    if args.agent_runtime_endpoint:
        command.extend(("--agent-runtime-endpoint", args.agent_runtime_endpoint))
    if args.agent_runtime_model:
        command.extend(("--agent-runtime-model", args.agent_runtime_model))
    if args.agent_runtime_loop:
        command.append("--agent-runtime-loop")
    if args.agent_runtime_allow_exec:
        command.append("--agent-runtime-allow-exec")
    if args.agent_runtime_memory:
        command.append("--agent-runtime-memory")
    if args.agent_runtime_session_history:
        command.append("--agent-runtime-session-history")
    if args.agent_runtime_max_steps != 40:
        command.extend(("--agent-runtime-max-steps", str(args.agent_runtime_max_steps)))
    if args.candidate_runner_command:
        command.extend(("--candidate-runner-command", args.candidate_runner_command))
    if args.agent_name != "evolution-agent":
        command.extend(("--agent-name", args.agent_name))
    if args.agent_role != "solver":
        command.extend(("--agent-role", args.agent_role))
    for capability in args.agent_capabilities:
        command.extend(("--agent-capability", capability))
    if args.evaluator_command:
        command.extend(("--evaluator-command", args.evaluator_command))
    if args.evaluator_agent_command:
        command.extend(("--evaluator-agent-command", args.evaluator_agent_command))
    for portfolio_command in args.evaluator_portfolio_commands:
        command.extend(("--evaluator-portfolio-command", portfolio_command))
    if args.evaluator_agent_name != "evolution-evaluator":
        command.extend(("--evaluator-agent-name", args.evaluator_agent_name))
    if args.evaluator_agent_role != "evaluator":
        command.extend(("--evaluator-agent-role", args.evaluator_agent_role))
    for capability in args.evaluator_agent_capabilities:
        command.extend(("--evaluator-agent-capability", capability))
    if args.openevolve_command:
        command.extend(("--openevolve-command", args.openevolve_command))
    for option, value in (
        ("--max-rounds", args.max_rounds),
        ("--stagnation-rounds", args.stagnation_rounds),
        ("--population-size", args.population_size),
        ("--offspring-per-iteration", args.offspring_per_iteration),
        ("--islands", args.islands),
        ("--migration-interval", args.migration_interval),
        ("--migration-rate", args.migration_rate),
        ("--seed", args.seed),
        ("--timeout", args.timeout),
    ):
        if value is not None:
            command.extend((option, str(value)))
    child_env = None
    if args.agent_runtime_api_key is not None:
        child_env = os.environ.copy()
        child_env["FAMOU_AGENT_RUNTIME_API_KEY"] = args.agent_runtime_api_key
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=child_env,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            store = Store(config.database)
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            store.set_runner_process(run_id, pid, pgid)
            latest = store.get_run(run_id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                store.clear_runner_process(run_id)
    except OSError as exc:
        Store(config.database).cancel_run(run_id)
        raise EvolutionError(f"could not start detached evolution run: {exc}") from exc
    return {
        "run_id": run_id,
        "status": "pending",
        "strategy": contract.evolution.strategy,
        "workspace": str(workspace),
        "detached": True,
    }


def _memory_payload(config: Config, query: str | None, scope: str | None, limit: int) -> list[dict[str, object]]:
    memory = MemoryStore(config.database)
    memory.initialize()
    if query:
        scopes = (scope,) if scope else ("global",)
        entries = memory.recall(query, scopes=scopes, limit=limit)
    else:
        entries = memory.list(scope=scope, limit=limit)
    return [
        {
            "id": entry.id,
            "scope": entry.scope,
            "kind": entry.kind,
            "content": entry.content,
            "tags": list(entry.tags),
            "source": entry.source,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "access_count": entry.access_count,
        }
        for entry in entries
    ]


def _answer(config: Config, args: argparse.Namespace) -> dict[str, object]:
    answer = args.answer
    if answer == "-":
        answer = sys.stdin.read()
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer requires non-empty text or '-' for stdin")
    api_key = args.api_key or os.environ.get("FAMOU_API_KEY")
    if api_key:
        answer = answer.replace(api_key, "[REDACTED]")
    if len(answer.encode("utf-8")) > 20_000:
        raise ValueError("answer exceeds 20 KiB")
    store = Store(config.database)
    run = store.get_run(args.run_id)
    if run is None:
        raise ValueError(f"unknown run: {args.run_id}")
    pending = store.pending_input(run.id)
    if pending is None:
        raise ValueError(f"run is not awaiting input: {args.run_id}")
    conversation = any(
        event["type"] == "conversation_started" for event in store.list_events(run.id)
    )
    manifest = _conversation_manifest(run) if conversation else None
    if conversation:
        current_fingerprint = _compiler_fingerprint(_controller(args, config).runtime)
        if manifest is not None and manifest.get("runtime_fingerprint") not in {
            None,
            current_fingerprint,
        }:
            raise ValueError("answer compiler runtime does not match the existing conversational run")
    artifacts = ArtifactStore(run.workspace, store, run.id)
    answer_path = artifacts.write_text(
        f"tasks/{pending['task_id']}/input-answer.json",
        json.dumps({"answer": answer.strip()}, ensure_ascii=False, indent=2) + "\n",
        pending["task_id"],
        kind="input",
    )
    relative_answer = str(answer_path.relative_to(run.workspace))
    task_id = store.answer_input(run.id, relative_answer)
    if task_id is None:
        raise ValueError("input request was answered concurrently; inspect status")
    controller = _controller(args, config)
    evolution_request = _latest_evolution_request(store, run.id)
    if conversation and run.current_plan_id is None:
        resumed = controller.resume_conversational(
            run.id,
            RuntimeContractCompiler(controller.runtime),
            compiler_fingerprint=_compiler_fingerprint(controller.runtime),
            plan_factory=_conversation_plan_factory(args, manifest),
            execute_plan=evolution_request is None,
        )
    else:
        resumed = controller.resume(run.id)
    evolution_request = _latest_evolution_request(controller.store, resumed.id)
    if resumed.current_plan_id is not None and evolution_request is not None:
        evolution_args = _evolution_args(args, evolution_request)
        # An OpenEvolve executable is intentionally not persisted in the request event. The
        # caller must continue that explicit strategy with ``solve --resume`` and provide the
        # command again; runtime-backed loop/population handoffs can resume automatically.
        if not (
            getattr(evolution_args, "strategy", None) == "openevolve"
            and not getattr(args, "openevolve_command", None)
        ):
            _solve_evolution(config, evolution_args, controller, resumed)
            resumed = controller.store.get_run(resumed.id) or resumed
    return {
        "run_id": resumed.id,
        "task_id": task_id,
        "status": resumed.status.value,
        "workspace": str(resumed.workspace),
        "answer_path": relative_answer,
        "workers": controller.max_workers,
        "evolution": _solve_payload(controller, resumed).get("evolution"),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _config(args)
        if args.command == "init":
            _emit({"home": str(config.home), "status": "initialized"}, args.json)
            return 0
        if args.command == "solve":
            payload = _solve(config, args)
            _emit(payload, args.json)
            success = payload["status"] in {"succeeded", "awaiting_input", "pending", "running"}
            evolution = payload.get("evolution")
            if isinstance(evolution, dict):
                success = success and evolution.get("status") in {
                    "succeeded",
                    "awaiting_input",
                    "pending",
                    "running",
                    "stagnated",
                }
            return 0 if success else 1
        if args.command == "run":
            plan_tasks = None
            if args.plan is not None:
                goal, plan_tasks = _load_plan(args.plan, args.goal)
            elif args.goal == "-":
                goal = sys.stdin.read()
            elif args.goal:
                goal = args.goal
            else:
                raise ValueError("run requires a goal or --plan PATH")
            if args.detach:
                _emit(_detach(config, args, goal, plan_tasks), args.json)
                return 0
            controller = _controller(args, config)
            run = controller.create(goal, plan_tasks)
            staged_inputs = _stage_input_files(run, controller.store, args.input_files)
            run = controller.resume(run.id)
            _emit(
                {
                    "run_id": run.id,
                    "status": run.status.value,
                    "workspace": str(run.workspace),
                    "input_request": controller.store.pending_input(run.id),
                    "input_data": list(staged_inputs),
                    "workers": controller.max_workers,
                },
                args.json,
            )
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "delegate":
            payload = _delegate(config, args)
            _emit(payload, args.json)
            return 0 if payload["run_status"] in {"succeeded", "pending"} else 1
        if args.command == "resume":
            controller = _controller(args, config)
            run = controller.resume(args.run_id)
            _emit(
                {
                    "run_id": run.id,
                    "status": run.status.value,
                    "workspace": str(run.workspace),
                    "input_request": controller.store.pending_input(run.id),
                    "workers": controller.max_workers,
                },
                args.json,
            )
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "evolve":
            payload = _evolve(config, args)
            _emit(payload, args.json)
            return 0 if payload.get("status") in {"completed", "stagnated", "pending"} else 1
        if args.command == "benchmark":
            payload = _benchmark(config, args)
            _emit(payload, args.json)
            return 0 if payload.get("status") == "completed" else 1
        if args.command == "answer":
            payload = _answer(config, args)
            _emit(payload, args.json)
            success = payload["status"] == "succeeded"
            evolution = payload.get("evolution")
            if isinstance(evolution, dict):
                success = success and evolution.get("status") in {
                    "succeeded",
                    "awaiting_input",
                    "pending",
                    "running",
                    "stagnated",
                }
            return 0 if success else 1
        if args.command == "status":
            if args.json:
                payload = _status_payload(config, args.run_id)
                if payload is None:
                    _emit_error(f"unknown run: {args.run_id}", True)
                    return 2
                _emit(payload, True)
                return 0
            return _print_status(config, args.run_id)
        if args.command == "events":
            if args.json:
                store = Store(config.database)
                if store.get_run(args.run_id) is None:
                    _emit_error(f"unknown run: {args.run_id}", True)
                    return 2
                _emit(store.list_events(args.run_id), True)
                return 0
            return _print_events(config, args.run_id)
        if args.command == "cancel":
            changed = _controller(argparse.Namespace(runtime="mock", runtime_command=None), config).cancel(
                args.run_id
            )
            if not changed:
                _emit_error(f"run not found or already terminal: {args.run_id}", args.json)
                return 2
            _emit({"run_id": args.run_id, "status": "cancelled"}, args.json)
            return 0
        if args.command == "recover":
            controller = LocalController(
                config,
                build_runtime("mock", None, None, None, None),
            )
            proposal = controller.recover(args.run_id)
            run = controller.store.get_run(args.run_id)
            assert run is not None
            _emit(
                {"run_id": run.id, "status": run.status.value, "proposal": proposal.to_dict()},
                args.json,
            )
            return 0
        if args.command == "memory":
            payload = _memory_payload(config, args.query, args.scope, args.limit)
            if args.json:
                _emit(payload, True)
            else:
                for entry in payload:
                    print(f"{entry['id']} [{entry['scope']}/{entry['kind']}] {entry['content']}")
            return 0
        if args.command == "decide":
            goal = sys.stdin.read() if args.goal == "-" else args.goal
            if not isinstance(goal, str) or not goal.strip():
                raise ValueError("decide requires a goal or '-' for stdin")
            _emit(MasterPolicy().decide(goal).to_dict(), args.json)
            return 0
        if args.command == "plan":
            candidate = Path(args.plan_file or args.target)
            if args.plan_file or candidate.is_file():
                document = _load_plan_document(candidate)
                controller = _controller(args, config)
                run = controller.start_plan(document)
                _emit({"run_id": run.id, "status": run.status.value, "plan_id": document.plan_id, "plan_version": document.version, "workspace": str(run.workspace), "workers": controller.max_workers}, args.json)
                return 0 if run.status.value == "succeeded" else 1
            payload = _status_payload(config, args.target)
            if payload is None:
                _emit_error(f"unknown run: {args.target}", args.json)
                return 2
            _emit(payload.get("plan"), args.json)
            return 0
        if args.command in {"patch", "replan"}:
            try:
                payload = json.loads(args.plan_file.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"could not read plan file {args.plan_file}: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"plan is not valid JSON: {exc.msg}") from exc
            controller = _controller(argparse.Namespace(runtime="mock", runtime_command=None, endpoint=None, model=None, api_key=None, agent_loop=False, memory=False, allow_exec=False, max_steps=40, session_history=False), config)
            if args.command == "patch":
                document = controller.patch_plan(args.run_id, PlanPatch.from_dict(payload))
                reason = "patch applied"
            else:
                if args.command == "replan" and "plan_id" not in payload:
                    current = controller.store.get_current_plan(args.run_id)
                    if current is None:
                        raise ValueError("run has no current plan")
                    payload = {**payload, "plan_id": current.plan_id}
                incoming = PlanDocument.from_dict(payload)
                raw_reason = payload.get("reason", "explicit replan")
                raw_evidence = payload.get("evidence", [])
                if not isinstance(raw_reason, str):
                    raise TypeError("replan reason must be a string")
                if not isinstance(raw_evidence, list) or any(not isinstance(item, str) for item in raw_evidence):
                    raise TypeError("replan evidence must be a string array")
                document = controller.replan(args.run_id, incoming, raw_reason, tuple(raw_evidence))
                reason = "replan applied"
            _emit({"run_id": args.run_id, "plan_id": document.plan_id, "plan_version": document.version, "parent_version": document.parent_version, "status": reason}, args.json)
            return 0
        if args.command == "deliver":
            controller = _controller(argparse.Namespace(runtime="mock", runtime_command=None, endpoint=None, model=None, api_key=None, agent_loop=False, memory=False, allow_exec=False, max_steps=40, session_history=False), config)
            decision = controller.deliver(args.run_id)
            _emit(decision.to_dict(), args.json)
            return 0
    except (AgentError, ValueError, TypeError, OSError, EvolutionError) as exc:
        _emit_error(str(exc), getattr(args, "json", False))
        return 2
    return 2
