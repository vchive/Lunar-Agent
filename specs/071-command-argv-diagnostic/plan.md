# Plan: Correctable Command Argument Diagnostics

1. Add failure-first tests for the observed nested JSON-array string, including leading whitespace,
   empty arrays and non-string members; assert no subprocess dispatch and no input echo.
2. Within the existing string branch of `_run_command`, detect a valid JSON array and raise a
   specific `ToolError` before `shlex.split`. JSON decode failures retain existing behavior.
3. Keep actual arrays and ordinary strings byte-for-byte compatible at the subprocess boundary,
   including `shell=False`, configured environment and deadline. Preserve the execution-disabled
   gate. Add a short schema clarification while preserving accepted types.
4. Exercise a real AgentLoop with a deterministic model and fake subprocess: bad string, feedback,
   corrected array, final text. Verify original transcript arguments and cumulative tools/usage.
5. Run targeted and full offline checks in the isolated worktree, independently review and commit
   the separate branch. Wait for Feature 069 termination and audit before integration.

## Decisions, alternatives and contracts

A corrective error keeps the declared distinction between an argv array and a command string.
Automatic nested parsing would turn an invalid request into an action without an explicit second
model choice, and is unnecessary here. A blanket `[` prefix rule would break ordinary commands.
Detection uses the already imported standard-library JSON module and examines only an input type;
there is no new dependency, state, receipt, artifact schema or migration.

The returned ToolResult remains unsuccessful with no artifacts. Its fixed diagnostic may change
the next model response, so it must not be introduced into an already registered measurement.
The failed call still consumes one tool step; the later corrected call is a second normal call.

## Verification

Use the repository's existing interpreter with explicit worktree source imports:

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest \
  -o addopts='' -q tests/test_command_argv_diagnostic.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check src/famou tests
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

Confirm `famou.tools.__file__` belongs to this worktree. Use deterministic model fixtures and a
fake subprocess; never execute historical model-produced commands. Run relevant runtime/budget/
transcript tests and the full suite before the branch is considered ready.

## Constitution review

No exception: a local, bounded standard-library validation branch with test-first runtime coverage,
unchanged subprocess authority and no persistent schema or runtime dependency change.
