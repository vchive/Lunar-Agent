# Lunar-Agent

Lunar-Agent is a standalone, local-first Famou agent controller. It keeps the durable task ledger
and artifacts in a run-scoped local directory and delegates one bounded unit of work through an
explicit Runtime Adapter. It does **not** require a machine-wide Hermes, OpenCode, or Codex
installation.

The project is being developed with Spec-Driven Development (SDD). Start with the feature artifacts
in [`specs/001-standalone-local-agent/`](specs/001-standalone-local-agent/): specification, plan,
research, data model, runtime contract, quickstart, and tasks.

## Bootstrap

Using [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

Using Python's standard environment tooling:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the standalone mock agent

```bash
uv run famou run "Create a durable local run report" --runtime mock
uv run famou status <run-id>
uv run famou events <run-id>
uv run famou resume <run-id>
```

The default home is `.famou/` in the current working directory. Set `FAMOU_HOME` or pass
`--home PATH` to use another local directory. The mock runtime is deterministic and requires no
network, credentials, model, or user-global Hermes state.

## Explicit external runtime

An external agent can be used only when explicitly configured:

```bash
export FAMOU_RUNTIME_COMMAND='my-agent --json'
uv run famou run "Inspect this repository" --runtime subprocess
```

The command receives the task prompt on stdin and runs inside the task workspace. Lunar-Agent never
searches for Hermes or imports `~/.hermes`.

## Development

```bash
uv run pytest
uv run --extra lint ruff check .
```

See the [quickstart](specs/001-standalone-local-agent/quickstart.md) for the recovery scenario and
the [runtime contract](specs/001-standalone-local-agent/contracts/runtime-adapter.md) before adding
an adapter.
