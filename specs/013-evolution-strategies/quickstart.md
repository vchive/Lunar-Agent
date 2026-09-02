# Quickstart: Local Evolution Strategies

## Prerequisites

```bash
cd /Users/liminghan/Documents/lunar_agent
uv run --extra dev pytest -q
```

No Hermes, OpenCode, Codex, Famou Workspace, network service, or OpenEvolve installation is needed
for the native strategies.

## Deterministic loop

The fixture generator emits one candidate per round and the fixture evaluator assigns a known score.
Run the test directly:

```bash
uv run pytest -q tests/test_evolution.py -k loop
```

Expected result: every candidate is present in `evolution/archive.jsonl`, and the result points to
the highest-scoring valid candidate, not necessarily the last round.

## Deterministic population

```bash
uv run pytest -q tests/test_evolution.py -k population
```

Expected result: the active population stays within its configured capacity, invalid candidates are
retained only for diagnostics, and archive history is never truncated.

## Optional OpenEvolve adapter

The adapter accepts an explicit executable. The test fixture acts as a local OpenEvolve-compatible
command:

```bash
uv run pytest -q tests/test_evolution.py -k openevolve
```

An absent command must fail closed. A real installation can be used only by passing its absolute
executable path through the adapter; it is not discovered from global agent configuration.

## Full verification

```bash
uv run pytest -q
uv run ruff check src tests
uv run python -m compileall -q src
```

See [evolution-strategy.md](contracts/evolution-strategy.md) for the persisted file layout and
result contract.

## Verification record

Feature 013 was verified locally with:

```text
uv run pytest -q                 125 passed
uv run --extra lint ruff check src tests   All checks passed
uv run python -m compileall -q src         passed
```
