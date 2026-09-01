# Quickstart: Standalone Local Famou Agent

This validation path uses only Python and the repository's deterministic mock runtime. It does not
require Hermes, OpenCode, Codex, a model key, or network access after dependencies are installed.

## Bootstrap

With `uv`:

```bash
uv sync --extra dev
```

With the Python standard library:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run a local goal

```bash
uv run python -m famou run "Create a durable local run report" --runtime mock
```

The command prints a run ID and stores the database and workspace below `.famou/` by default.

## Inspect and resume

```bash
uv run python -m famou status <run-id>
uv run python -m famou events <run-id>
uv run python -m famou resume <run-id>
```

To exercise recovery, stop a run after its task has been persisted, then run `resume`. The resumed
run must reach `succeeded` without creating a second terminal result or duplicate artifact.

## Test

```bash
uv run pytest
```

The tests use temporary directories and the mock runtime. They must pass on a clean machine without a
global `.hermes` directory.

## Optional external runtime

Set an explicit command when using a separately installed agent:

```bash
export FAMOU_RUNTIME_COMMAND='my-agent --json'
uv run python -m famou run "Inspect this repository" --runtime subprocess
```

The command receives the task prompt on stdin and runs with the task workspace as its current working
directory. The repository does not discover Hermes or import user-global agent state.
