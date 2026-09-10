# Plan: Master Budget Measurement

## Decisions and alternatives

Use the existing StagePolicy support without a product change. A fresh 300-second control avoids
confounding the comparison with Features070/071. Four staged slots answer the budget question;
another normal arm, stronger models, prompt changes or retries would broaden it unnecessarily.
Reuse pinned Feature069 execution/receipt/audit helpers through explicitly isolated module
adapters, replacing hardcoded registration, per-slot binding and grouping orchestration only.
Never mutate an old manifest to satisfy its checker; preserve all historical bytes.

## Data model and contracts

The new campaign is .lunar/real-eval-glm-5.2-master-budget-20260910. Its immutable manifest keeps
arm=S on all slots, adds budget_arm, and replaces global policy with policies keyed master_300
and master_1200. Each workflow binds its own run/attempt/request/source/profile/case and exact
registered policy. All actually imported old scripts and new wrappers are frozen dependencies.
Existing native request/receipt/state schemas, executor and scoring semantics remain unchanged;
there is no migration. Independent preaudit checks actual private harness bytes and source Git
blobs. Summary accepts only the existing native outcome/record/state/report/receipt chain.
Postrun evidence records phase reachability conservatively with exact Master duration null.

## Ordered implementation and verification

1. Write spec and dependency-ordered tasks; build new prepare/audit/dry-run orchestration.
2. Implement isolated reuse, exact per-slot bindings and budget-group summaries with offline tests.
3. Add postrun orchestration and phase evidence verification outside frozen execution scripts.
4. Run relevant and full offline suites, Ruff, Specify and independent review. Materialize once;
   audit and dry-run the exact registration, then commit and push before any dispatch.
5. Launch once, observe without changing frozen files, finish all four slots and independently seal
   final per-case results. Never retry a failed slot or revise historical outcomes.

## Runnable quickstart

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/test_measurement072*.py tests/test_staged*.py
.venv/bin/python specs/072-master-budget-measurement/measurement/prepare.py
.venv/bin/python specs/072-master-budget-measurement/measurement/campaign.py --check-only
.venv/bin/python specs/072-master-budget-measurement/measurement/campaign.py --dry-run
# Persist and independently review reports, commit/push registration, then launch exactly once:
.venv/bin/python specs/072-master-budget-measurement/measurement/campaign.py --launch
# While running, only use read-only observation:
.venv/bin/python specs/072-master-budget-measurement/measurement/campaign.py --summarize
```

## Constitution / complexity tracking

No exception. No product runtime or dependency change; credential-free immutable registration,
bounded existing runner, test-first transitions and independent artifact verification apply.
Precise per-stage timing and crash recovery remain unsupported; this experiment does not add them.
