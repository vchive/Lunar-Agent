# Validation

## Status

Implementation and focused/shared-runtime verification are complete; final full-regression and
documentation checks are recorded below.

## Required focused checks

- Unprofiled `AgentLoopRuntime.run` exposes `tool_steps_remaining` on the first request and reduces
  it after accepted tool calls; `tokens_remaining` and `cost_micros_remaining` are `null`.
- A bounded timeout exposes a positive, decreasing `remaining_seconds`; an unbounded timeout keeps
  it `null`. Request timeout arguments and existing tool execution deadlines remain unchanged.
- Captured request messages contain one advisory on each current provider request while the source
  messages and session transcript remain byte-identical and contain no `lunar_runtime_budget` text.
- Profiled normal runs retain their current snapshot and usage enforcement; isolated runs remain
  advisory-free.
- A rejected multi-call response raises the typed step-limit error, emits bounded structured
  evidence, and leaves tool calls, assistant history, transcript, artifacts and memory untouched.
  No second provider request is made and no fitting prefix is executed.
- A nonempty tool-free final response succeeds at zero remaining tool steps; empty final text still
  raises the existing completion error.

## Commands

```sh
.venv/bin/python -m pytest tests/test_agent_loop.py tests/test_runtime.py tests/test_interactive.py \
  tests/test_agent_evolution.py tests/test_master_planning_role_integration.py
.venv/bin/ruff check src/lunar_evolution/agent_loop.py tests/test_agent_loop.py tests/test_runtime.py
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature135
```

## Results

- Focused agent-loop and budget tests: passed.
- Shared runtime, interactive, evolution, staged-loop and master-planning tests: passed.
- Ruff, compileall and `git diff --check`: passed.
- Full current regression: `7927 passed, 1 skipped, 24 deselected`.
- Frozen historical regression: `24 passed`.
- Feature 134 retained measurement files were not modified.

## Historical and scope checks

The final review must confirm that no Feature 134 manifest, measurement, postrun result, audit,
diagnosis, report or evidence file changed. No provider request, campaign rerun, generated source
execution or historical artifact replay is part of offline validation. Passing these checks proves
request visibility and diagnostic integrity; it does not prove that a real model will heed the
advisory or that a future multi-file campaign will deliver a candidate.
