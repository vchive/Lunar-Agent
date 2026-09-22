# Validation

## Status

Implementation complete and focused offline-validated as of 2026-09-18. No provider request,
campaign, evaluator call, generated-source execution, or Feature 134 resume is part of this
feature.

## CI fixture follow-up, 2026-09-22

The prior Linux matrix exposed one Python 3.12 failure in the synchronous two-task fixture:
the test used a real 0.25-second wall budget, so CI startup and filesystem scheduling could
consume the budget before the second request. The controller path remained within the feature
contract, which defines one deadline per `resume()` execution. The fixture now injects the
existing deterministic controller clock and advances it from the simulated runtime delay. This
preserves the assertions that both requests share one deadline and that the second timeout is
smaller, without making the outcome depend on host load. The focused wall-clock module passes
locally. The post-fix [Linux CI Run 221](https://github.com/vchive/Lunar-Evolution/actions/runs/35692074592)
completed successfully for Python 3.11, 3.12, and 3.13.

## Required focused checks

- `run_agent()` validates the existing explicit/configured timeout, clips it to the run remainder,
  and sends that value in `AgentRequest`. A non-positive remainder fails before task claim and
  adapter invocation with the existing `max_runtime_seconds` evidence.
- Synchronous `resume()` uses one deadline for all tasks. A later task receives only the current
  remainder, and an exhausted deadline prevents further claims without a fresh per-task budget.
- Concurrent `resume()` workers use the same deadline. Recorded runtime timeouts are bounded by
  their invocation-time remainder; one worker's budget failure creates one durable event and all
  active workers unwind cleanly.
- Candidate-generation requests, explicit delegation timeout validation, runtime profiles,
  process observers, and cancellation fan-out retain their existing contracts. No timeout is
  written into replayable messages, transcripts, `Config`, `BudgetSpec`, or a frozen profile.
- Late runtime results retain current bounded local artifact behavior but cannot promote success,
  create a retry, or deliver outputs after the post-request budget guard observes exhaustion.
- The cancellation-race fixtures cover both durable winners: cancellation first discards a result
  returned after the clipped request timeout, while a budget failure first rejects a later cancel
  and leaves the run failed, its task blocked, and its single `budget_exceeded` event intact.
- Cancellation races preserve whichever Store transition is durable first. Late results are
  discarded, cancellation callbacks all run, process groups are cleaned, and no second budget
  event or terminal-state rewrite appears.
- Existing controller, agent, runtime, retry, evaluator, and budget regressions pass. Feature 134
  registration, manifest, measurement, postrun, report, results, audit, and evidence files retain
  exact sizes and SHA-256 values.

## Planned commands

```sh
PYTHONPATH=. .venv/bin/pytest -q tests/test_controller.py tests/test_agents.py \
  tests/test_runtime.py tests/test_budget_failure_evidence.py tests/test_budget_aware_tools.py \
  tests/test_run_wall_clock_budget.py
.venv/bin/ruff check src/lunar_evolution/controller.py src/lunar_evolution/agents.py \
  tests/test_controller.py tests/test_run_wall_clock_budget.py
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature137
```

The new `tests/test_run_wall_clock_budget.py` module may be folded into the existing controller
test module if repository conventions make that clearer. Fixtures must use local scripted runtimes, synthetic clocks and
temporary workspaces. The full regression must include its frozen historical stage; a passing
offline suite demonstrates local timeout propagation only and says nothing about provider-side
completion, usage, quality, or WebAgent parity.

## Completed validation

- Feature 137 focused fixture/controller/adapter/runtime/budget tests: `116 passed`.
- The Feature 137 focused suite now includes the cancellation-first and budget-first race fixtures;
  the local focused controller/plan/store regression passes with `39 passed`.
- Ruff, `python -m compileall -q src tests`, Specify prerequisites, and `git diff --check`
  passed.
- Full current regression: `7941 passed, 1 skipped, 24 deselected`; frozen Feature 123 stage:
  `24 passed`. Both JUnit stages reported zero failures and zero errors.
- Feature 134 specification and retained campaign paths are absent from the working-tree diff;
  the frozen regression verified 77 product, 14 measurement, and 69 historical pinned files.
- No provider request, campaign, evaluator call, generated-source execution, or Feature 134
  resume was started.

## Preservation checks

Before implementation commit, compare the Feature 134 evidence inventory and all registered
measurement hashes against the retained inventory. Any changed historical file is a stop
condition. Do not run the Feature 134 worker, replay captured responses, inspect private model
text, append another attempt, or launch a real campaign.

## Expected result recording

The full two-stage totals and independent historical inventory are recorded in the handoff after
the final regression. Note that local clipping cannot prove a remote provider stopped and that a
synchronous operation may finish before the next controller budget boundary observes the deadline.
