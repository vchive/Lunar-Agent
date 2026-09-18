# Validation

## Status

Implementation complete and validated offline on 2026-09-18. No provider request, campaign
resume, generated-source execution, or historical evidence rewrite was part of this feature.

## Required focused checks

- Candidate generation rejects a missing, zero, negative, non-integer, non-finite, or out-of-range
  budget before adapter invocation and exposes one authority-bound budget identity.
- A deterministic `4 + 2` fixture raises the existing typed step-limit boundary, emits one bounded
  candidate diagnostic, and proves that the rejected batch causes no tool, transcript, artifact,
  memory, candidate-record, evaluator, or delivery side effect.
- A successful multi-turn fixture reports `completed` only after a nonempty tool-free response and
  parser acceptance; a tool-bearing response never counts as the final candidate.
- Tool failure, bounded command/model timeout, cancellation, empty final response, malformed
  candidate JSON/shape, and generic worker failure each produce the specified distinct outcome with
  no arbitrary error prose or private content.
- Repeated provider requests receive one current candidate-scoped budget advisory; original
  messages, replayable transcript, and durable state remain unchanged and contain no stale copy.
- Existing profiled runtime budget accounting, `run_isolated`, deterministic generators, bundle
  integrity, candidate execution/evaluation, resume, and parent delivery regressions pass.
- Feature 134 registration, manifest, measurement, postrun, evidence, report, diagnosis, audit,
  and results files retain their original byte sizes and SHA-256 inventory.

## Planned commands

```sh
PYTHONPATH=. .venv/bin/pytest -q tests/test_agent_loop.py tests/test_agents.py \
  tests/test_agent_evolution.py tests/test_agent_bundle_generation.py tests/test_controller.py \
  tests/test_budget_aware_tools.py
.venv/bin/ruff check src/famou/agent_loop.py src/famou/agents.py \
  src/famou/agent_evolution.py src/famou/agent_bundle_generation.py \
  tests/test_agent_loop.py tests/test_agents.py tests/test_agent_evolution.py
.venv/bin/python -m compileall -q src tests
bash .specify/scripts/bash/check-prerequisites.sh
git diff --check
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature136
```

The full regression must include the frozen historical stage. A passing offline suite demonstrates
diagnostic and authority behavior only; it does not prove that a future model will heed the
advisory or that any selected budget is sufficient for a real multi-file delivery.

## Completed validation

- Focused Agent-loop, adapter, single-file generation, bundle generation, controller, and
  budget-aware tooling tests: `105 passed`.
- Ruff passed for all changed source and test files.
- `python -m compileall -q src tests` passed.
- `git diff --check` passed.
- Feature 134 files are absent from the working-tree diff; no retained registration, manifest,
  postrun, evidence, or measurement file was modified.
- The full repository collection reached 100% with 24 expected historical registration-fixture
  errors: Feature 123 deliberately rejects a dirty product against its pinned `PRODUCT_COMMIT`.
  Those errors are a pre-commit working-tree guard, not Feature 136 failures; the Feature 136
  shared regression above is green.
- No real campaign, provider request, evaluator call, or candidate execution was started.

## Preservation checks

Before commit, compare the Feature 134 evidence inventory and all registered measurement hashes
against its retained inventory. Any changed historical file is a stop condition. Do not run the
Feature 134 worker, inspect private model text, replay captured responses, or append another attempt.
