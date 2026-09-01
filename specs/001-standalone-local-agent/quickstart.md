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

## Run a dependent plan

Create `plan.json`:

```json
{
  "goal": "prepare a report",
  "tasks": [
    {"id": "research", "title": "Research", "prompt": "Collect facts"},
    {"id": "write", "title": "Write", "prompt": "Draft the report", "depends_on": ["research"]}
  ]
}
```

Then execute it with:

```bash
uv run python -m famou run --plan plan.json --runtime mock --json
```

The `write` task is not claimed until `research` has a verified result. Its prompt contains the
run-relative result path and a bounded text preview of predecessor artifacts. Duplicate IDs,
unknown dependencies, and cycles are rejected before a run is inserted.

## Agent-to-agent invocation

Use the JSON mode when Codex or another Agent invokes Lunar-Agent as a child process:

```bash
uv run python -m famou run "Create a local report" --runtime mock --json
uv run python -m famou status <run-id> --json
```

The `run --json` and `status --json` commands are intentionally independent of Python imports or
Hermes installation. If the parent process times out, it should retain the returned run ID and call
`resume` or `status` instead of starting a duplicate run.

For a long-running child process, use:

```bash
uv run python -m famou run "Long analysis" --runtime subprocess --detach --json
```

This returns before execution completes. Poll `status --json`, inspect `events --json`, or call
`cancel` with the returned run ID; the detached controller writes its log in the run workspace.
`cancel` terminates the persisted detached process group, and a late result is discarded with a
`task_result_discarded` event.

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

## Optional local model server

The repository includes a standard-library OpenAI-compatible adapter. Configure a local Ollama,
vLLM, or LM Studio endpoint explicitly:

```bash
export FAMOU_MODEL_ENDPOINT='http://127.0.0.1:11434/v1/chat/completions'
export FAMOU_MODEL='your-local-model'
uv run python -m famou run "Inspect this repository" --runtime openai-compatible --agent-loop --json
```

`--endpoint` and `--model` are equivalent flags. An API key is optional for local servers and can be
provided through `FAMOU_API_KEY`; it is never written to the ledger or controller log. The HTTP
adapter requires a non-empty text response and applies the same evaluator/retry policy as other
runtimes. Add `--allow-exec` for bounded no-shell command execution. Add `--memory` to explicitly
enable the local `recall_memory` and `remember_memory` tools; memory notes are stored in SQLite and
are never injected into a model request silently.
