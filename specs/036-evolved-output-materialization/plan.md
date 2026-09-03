# Implementation Plan: Evolved Output Materialization

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Technical context

`LocalController.run_evolution` already produces a strict `StrategyResult`; `CommandCandidateRunner`
already records bounded process evidence; the output evaluator and Solver promotion path already
understand `OutputSpec`. The change composes these boundaries after the linked evolution finishes
instead of introducing a second executor, evaluator DSL, or task service.

## Decisions

1. **A distinct final phase** — search-time execution answers “is this candidate competitive?”;
   materialization answers “did the selected candidate produce this contract's deliverable data?”
   The latter always re-executes the winner in a fresh directory and revalidates outputs.
2. **Python protocol for automatic handoff** — conversational evolution asks for a self-contained
   `.py` candidate. It is invoked as `<sys.executable> -I <candidate>` from the attempt directory.
   The candidate reads `data/raw/*` and writes exact declared `output/*` paths using the standard
   library. Unsupported source types fail with an explicit bounded result.
3. **Two-run ownership** — execution evidence and the durable materialization result live under the
   evolution child; promoted output files and `kind=output` ledger rows live under the intake parent.
4. **Validation before promotion** — build `output_valid` rules directly from the immutable parent
   contract. Required outputs are always checked; optional outputs are checked when present. No
   process claim or evolution report can bypass this evaluator.
5. **Deterministic idempotency** — the attempt path is derived from the selected candidate ID and
   source digest. A terminal result is reusable only after all identities and output digests are
   rechecked. Existing different parent bytes fail closed rather than being overwritten.
6. **Composite status, unchanged schema** — parent and child remain valid independent ledgers.
   `solve` reports materialization failure as its effective status, while `run_status` preserves the
   intake row. `status` carries the same linked materialization payload. No database migration is
   needed.

## Data flow

```text
intake run: AlgorithmProblemContract.outputs + staged inputs
             | copy by digest
             v
evolution child: archive -> best candidate source
             | copy source + inputs
             v
evolution/materialization/<candidate>-<digest>/
             | python -I candidate.py
             | execution.json + attempt-local output/*
             v
independent OutputSpec validation
             | pass only
             v
intake run/output/* -> SHA-256 ledger -> status/deliver
```

## Safety and recovery

- Candidate source, input, output, marker, and destination paths reject symlink components and
  traversal. The subprocess has no shell and receives a minimal non-secret environment.
- Existing output files are immutable at this boundary: equal bytes are reused, unequal bytes are
  a conflict. Promotion uses a same-directory temporary file and atomic replacement.
- A result is written only after execution/validation/promotion reaches a terminal decision. On a
  process crash before that marker, the deterministic attempt is cleaned only after validating its
  exact confined location, then restarted; terminal markers are never silently retried.
- Events contain bounded metadata and deterministic IDs, so replay does not create duplicate link
  or promotion meaning.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Uses the repository Python process and standard library only. |
| Local-First and Durable State | Pass | Child evidence and parent hashes survive restart. |
| Runtime Adapter Isolation | Pass | Search runtimes remain adapters; final execution has its own protocol. |
| Artifact-First Verification | Pass | Contract data, not prose or model score, is delivery authority. |
| Bounded Autonomy | Pass | Time, bytes, paths, environment, and promotion are bounded. |
| Test-First Recovery | Pass | Tests cover invalid outputs, conflicts, and terminal replay. |

## Complexity tracking

The materialization phase is deliberately controller-owned because it joins two durable runs and
the final artifact ledger. It reuses the existing candidate runner and acceptance evaluator rather
than hiding this cross-run transaction in an Agent adapter. Portable hard memory/CPU isolation is
not claimed; stronger sandboxing remains a future explicit runner adapter.
