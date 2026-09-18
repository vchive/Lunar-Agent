# Implementation Plan: Public status projection and preparation recovery

**Date**: 2026-09-18  
**Spec**: [spec.md](spec.md)

## Technical approach

1. Trace the existing status payload/text path in `src/famou/cli.py` and preparation recovery
   decisions in `src/famou/automatic_solve_bundle.py`; preserve the Feature 116/132 persisted
   `running` recovery contract.
2. Introduce a small bounded status projector that keeps persisted parent, preparation, and
   effective status separate. Reuse current precedence and typed diagnostic validators; do not
   persist a derived status or mutate Store rows while reading.
3. Extend the measurement transport summary to project the already validated HTTP status from a
   single bound exchange. Keep schema compatibility for older results and reject ambiguous or
   private rows.
4. Add offline fixtures for every status/recovery branch and for successful, error, timeout, and
   malformed transport records. Assert no provider call, no generated-source execution, and no
   historical evidence changes.
5. Run focused regressions, Ruff, compileall, Specify checks, and the full two-stage suite before
   commit. Independently inventory Feature 131/134 bytes, then commit and push.

## Touch points

- `src/famou/cli.py`
- `src/famou/automatic_solve_bundle.py`
- `specs/134-budgeted-multifile-acceptance/measurement/analysis.py` and any shared projector
- preparation/status and measurement analysis tests

## Alternatives rejected

- Rewriting a recoverable parent row to `failed` would break explicit contract reuse.
- Inferring HTTP status from ledger success or usage would fabricate remote evidence.
- Updating Feature 131 results in place would invalidate its retained measurement boundary.
- Adding automatic retries would change registered request counts and failure denominators.

## Verification strategy

Use local Store fixtures and synthetic transport ledgers. Assert exact status precedence, resume
admission, request counts, redaction, and historical byte/SHA preservation. No provider request,
campaign, evaluator call, or generated-source execution is permitted.
