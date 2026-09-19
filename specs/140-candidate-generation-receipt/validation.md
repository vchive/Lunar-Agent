# Validation

Implementation and validation completed without calling a provider, evaluator, or executing
generated source. The controller now retains one bounded `agent_candidate_generation` event per
`run_id/task_id/budget_id`, with a deterministic event ID and an atomic Store append. Completed
events require parser completion, candidate identity, source-bundle digest, and exact tool-budget
arithmetic; failed/unknown events cannot carry candidate or source identity. Schema, stage, task
ownership, duplicate, tamper, identity, and missing-receipt checks fail closed.

Validation completed for the implementation boundary:

- Feature 140 receipt and integration focus, Agent/bundle, and Feature 139 offline suites passed.
- Ruff, `compileall`, and `git diff --check` passed.
- No provider request, evaluator invocation, generated-source execution, or Feature 139
  registration was performed.

The repository-wide `PYTHONPATH=. .venv/bin/pytest -q` run is not green: 24 legacy
`measurement123` setup cases reject the current product commit with `ValueError: product_changed`.
Those tests intentionally pin an older product snapshot and were not changed. The historical
snapshot must be tested from its pinned checkout before T005 can close.

Feature 139 remains blocked from real registration until this pushed change is available to its
native controller path and a separately authorized measurement is prepared.
