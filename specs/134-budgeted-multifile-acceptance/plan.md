# Implementation Plan: Budgeted multi-file acceptance

**Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)

## Summary and technical context

Use a new campaign-local copy of the reviewed Feature 131 harness with product pinned to Feature
133. Python 3.11+, standard library and pytest; local macOS worker, SQLite retained state and file
artifacts. No new dependency or product changes. Root is `.lunar/acceptance134-glm-5.2-budgeted-multifile-20260918`.

## Constitution check

Standalone/local-first runtime remains unchanged. Only the explicit runtime adapter calls the
configured provider; secret values never enter registered/public data. Native independent scoring
and delivery validation decide success. One attempt has fixed time/request/observed-token bounds,
and process supervision verifies cleanup. Offline failure/recovery tests precede launch. All six
constitutional principles apply without exceptions; remote calls follow the user's proceed request.

## Decisions and alternatives

- Preserve the same task and overall 2400-second/20-request/160000-observed-token ceilings.
  Raise only preparation requests to 900 seconds and set preparation wall to 1860 seconds.
  Candidate/ordinary requests stay 600 seconds. Increasing the shared candidate timeout would
  change an unrelated authority; silently retaining a 600-second outer cap would negate Feature 133.
- Keep the frozen Feature 113 shared accounting code untouched. The new observer/worker must
  enforce stage limits without weakening the ledger or request-stop behavior, and preserve exact
  typed native request errors after durable accounting when applicable.
- Copy the campaign rather than mutate prior evidence. New analysis accepts safe Feature 132/133
  diagnostics and projects successful HTTP status; no historical report is rewritten.
- Local holdouts remain conditional on verified preparation and remaining campaign time, independent
  of stopped model admission. Only completed/clean results receive official quality.

## Data model and contracts

See [data-model.md](data-model.md) and [contracts/measurement.md](contracts/measurement.md). Registration
adds separate candidate/preparation request/preparation wall limits to the existing global request
and wall bounds. Fixed references bind prior preparation128 and attempt131. All registered docs,
measurement Python and tests are pinned; mutable tasks/validation/postrun reporting stay outside
the preregistration pin set. Native preparation handoff values must match registered budgets.

## Structure and execution

`measurement/{case,observation,supervision,campaign,worker,analysis}.py` and
`tests/test_measurement134_*.py` implement this campaign only. Adapt the copied fixtures before
implementation; prove request routing, failures, policy binding, safe status and read-only analysis.
Run focused/full regression, Feature 112 quickstart, static checks and independent review. Then
prepare/verify manifest without model calls, commit/push and verify `HEAD == origin/main` before
the sole run. Summarize once; independently audit retained evidence, update report/roadmap/handoff,
commit and push. Commands are in [quickstart.md](quickstart.md).

## Complexity tracking

No constitutional exception, dependency, database migration or external search framework.
