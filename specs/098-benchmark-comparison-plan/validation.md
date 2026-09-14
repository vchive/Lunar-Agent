# Validation — 2026-09-15

## Results

- Failure-first collection was performed before the comparison module existed.
- 097 task-envelope plus 098 comparison-plan and benchmark/CLI regression tests: **82 passed** in 9.23s.
- Ruff (with import formatting), compileall and diff check passed.
- No CLI runner, external framework, model, provider, remote service or campaign was started.
- The existing benchmark runner and sealed measurement files were not changed.

## Behaviors exercised

- Two framework arms with different benchmark names share one task comparison identity and produce a
  stable derived comparison ID.
- Duplicate JSON keys and nonfinite values are rejected; arm IDs are safe and unique.
- Contract, task, candidate, model, evaluator or budget drift between arms is rejected before input
  admission. Each arm is reparsed canonically before 097 read-only admission.
- Input files are checked for confined regular paths, exact size and SHA-256. Caller contract,
  model, evaluator and optional budget pins are required and compared.
- Admission returns only arm IDs and digests; per-arm attempt limits remain isolated and no producer,
  evaluator, model, scheduler or Store is invoked.

## Scope and retained limits

The plan freezes comparison conditions but does not execute or compare framework effectiveness.
Scores, generation IDs and run IDs are excluded from comparison identity. Repository/workflow,
training/RL and remote lifecycle candidates require separate contracts.
