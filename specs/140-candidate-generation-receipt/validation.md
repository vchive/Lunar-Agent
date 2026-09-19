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

## Follow-up validation closure (2026-09-19)

Feature 141 ran the repository split regression, resolving the historical-checkout requirement
above: current product 8166 passed, 1 skipped, 24 deselected; immutable Feature 123 product
24 passed, no skips; overall exit 0. Historical file pins and Feature 131/134 retained inventories
matched. The combined Feature 141/139/140 focused suite passed 409 tests. No real provider request
or historical campaign was replayed; repository-owned synthetic fixtures ran locally.

Feature 141 also connects the explicit budget to the native automatic multi-file CLI and corrects
completion receipt arithmetic under a lower runtime profile. Feature 139 still requires its own
sealed manifest, observer/supervisor, budget/request bindings, and preregistration audit closure.
