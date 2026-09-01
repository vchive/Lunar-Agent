"""Command-line interface for the standalone local controller."""

from __future__ import annotations

import argparse
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="famou",
        description="Standalone local Famou agent controller",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a local state directory")
    _add_home(init_parser)

    run_parser = subparsers.add_parser("run", help="start and execute a goal")
    run_parser.add_argument("goal", help="user goal")
    run_parser.add_argument("--runtime", choices=("mock", "subprocess"), default="mock")
    run_parser.add_argument("--command", dest="runtime_command", help="explicit subprocess command")
    _add_home(run_parser)

    resume_parser = subparsers.add_parser("resume", help="recover and continue a run")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--runtime", choices=("mock", "subprocess"), default="mock")
    resume_parser.add_argument("--command", dest="runtime_command", help="explicit subprocess command")
    _add_home(resume_parser)

    for name, help_text in (
        ("status", "inspect a run"),
        ("events", "inspect run events"),
        ("cancel", "cancel a run"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument("run_id")
        _add_home(command_parser)
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


def _print_events(config: Config, run_id: str) -> int:
    store = Store(config.database)
    if store.get_run(run_id) is None:
        print(f"unknown run: {run_id}", file=sys.stderr)
        return 2
    for event in store.list_events(run_id):
        task = f" task={event['task_id']}" if event["task_id"] else ""
        print(f"{event['created_at']} {event['type']}{task} {event['payload']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = _config(args)
        if args.command == "init":
            print(f"initialized: {config.home}")
            return 0
        if args.command == "run":
            run = _controller(args, config).start(args.goal)
            print(f"run_id: {run.id}")
            print(f"status: {run.status.value}")
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "resume":
            run = _controller(args, config).resume(args.run_id)
            print(f"run_id: {run.id}")
            print(f"status: {run.status.value}")
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "status":
            return _print_status(config, args.run_id)
        if args.command == "events":
            return _print_events(config, args.run_id)
        if args.command == "cancel":
            changed = _controller(argparse.Namespace(runtime="mock", runtime_command=None), config).cancel(
                args.run_id
            )
            if not changed:
                print(f"run not found or already terminal: {args.run_id}", file=sys.stderr)
                return 2
            print(f"cancelled: {args.run_id}")
            return 0
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2
