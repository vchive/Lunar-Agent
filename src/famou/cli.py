"""Command-line interface for the standalone local controller."""

from __future__ import annotations

import argparse
import json
import sys

from .config import Config
from .controller import LocalController
from .runtime import build_runtime
from .store import Store


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
    run_parser.add_argument("goal", help="user goal, or '-' to read it from stdin")
    run_parser.add_argument("--runtime", choices=("mock", "subprocess"), default="mock")
    run_parser.add_argument("--command", dest="runtime_command", help="explicit subprocess command")
    _add_home(run_parser)
    _add_json(run_parser)

    resume_parser = subparsers.add_parser("resume", help="recover and continue a run")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--runtime", choices=("mock", "subprocess"), default="mock")
    resume_parser.add_argument("--command", dest="runtime_command", help="explicit subprocess command")
    _add_home(resume_parser)
    _add_json(resume_parser)

    for name, help_text in (
        ("status", "inspect a run"),
        ("events", "inspect run events"),
        ("cancel", "cancel a run"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument("run_id")
        _add_home(command_parser)
        _add_json(command_parser)
    return parser


def _config(args: argparse.Namespace) -> Config:
    config = Config.from_env(args.home)
    config.ensure()
    Store(config.database).initialize()
    return config


def _controller(args: argparse.Namespace, config: Config) -> LocalController:
    runtime = build_runtime(args.runtime, getattr(args, "runtime_command", None))
    return LocalController(config, runtime)


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
    for task in store.list_tasks(run.id):
        print(
            f"task: {task.id} state={task.state.value} attempts={task.attempts}"
            + (f" error={task.last_error}" if task.last_error else "")
        )
    artifacts = store.list_artifacts(run.id)
    for artifact in artifacts:
        print(
            f"artifact: {artifact['path']} size={artifact['size']} sha256={artifact['sha256']}"
        )
    return 0


def _status_payload(config: Config, run_id: str) -> dict[str, object] | None:
    store = Store(config.database)
    run = store.get_run(run_id)
    if run is None:
        return None
    return {
        "run": {
            "id": run.id,
            "goal": run.goal,
            "status": run.status.value,
            "workspace": str(run.workspace),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        },
        "tasks": [
            {
                "id": task.id,
                "run_id": task.run_id,
                "title": task.title,
                "state": task.state.value,
                "attempts": task.attempts,
                "result_path": str(task.result_path) if task.result_path else None,
                "last_error": task.last_error,
            }
            for task in store.list_tasks(run.id)
        ],
        "artifacts": store.list_artifacts(run.id),
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _config(args)
        if args.command == "init":
            _emit({"home": str(config.home), "status": "initialized"}, args.json)
            return 0
        if args.command == "run":
            goal = sys.stdin.read() if args.goal == "-" else args.goal
            run = _controller(args, config).start(goal)
            _emit(
                {
                    "run_id": run.id,
                    "status": run.status.value,
                    "workspace": str(run.workspace),
                },
                args.json,
            )
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "resume":
            run = _controller(args, config).resume(args.run_id)
            _emit(
                {
                    "run_id": run.id,
                    "status": run.status.value,
                    "workspace": str(run.workspace),
                },
                args.json,
            )
            return 0 if run.status.value == "succeeded" else 1
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
    except (ValueError, OSError) as exc:
        _emit_error(str(exc), getattr(args, "json", False))
        return 2
    return 2
