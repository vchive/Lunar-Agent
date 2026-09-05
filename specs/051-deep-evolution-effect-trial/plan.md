# Implementation Plan: Matched Deep-Evolution Effect Trial

**Branch**: `main` | **Date**: 2026-09-05 | **Spec**: [spec.md](spec.md)

## Technical context

Feature 048's `EffectTrialRunner` already owns suite/baseline identity checks, safe public staging,
control copies, command invocation, and exact harness integration. The deep runner subclasses that
boundary and changes only the logical-run execution, record schema, and report aggregation. The
normal runner is not parameterized and its score/report schemas remain unchanged; the shared rule
that only state-registered logical records are authoritative is hardened for both protocols.

The built-in subject adapter accepts a second request mode, `deep_evolution`. It runs one fresh
repository-owned Agent loop per outer round with the same attempt workspace. This gives the model a
safe continuation boundary through files and explicit bounded `RoundFeedback` while keeping
memory/session history disabled.

## Decisions

1. **Five rounds by default** — encode WebAgent's no-argument `/evolve` source default in a public
   `DeepEffectTrialConfig`; allow a bounded override for deterministic fixtures.
2. **Round-level scoring** — run the frozen extractor/evaluator after each round instead of only at
   the end, making improvement curves observable and preventing a final-only score from hiding
   stagnation or regressions.
3. **Fresh process, shared workspace** — each subject round is a fresh invocation, while artifacts
   and the previous bounded feedback persist inside the logical attempt. No global Agent discovery
   or machine Hermes state is used.
4. **Best-of-round semantics** — a logical run's score is the maximum evaluator-valid round score;
   validity/quality are taken from the winning round. Invalid rounds remain in the audit record.
5. **Reuse exact harness** — the deep protocol passes normal Feature 049 harness requests with a
   round-specific sibling workspace, so digest, credential, and extractor behavior stay identical.
6. **Durable round authority** — only a persisted round record permits reuse of its harness result.
   Unrecorded harness output is discarded and rescored by the exact private harness.
7. **Bound subject continuation** — reusing an unrecorded subject round requires a request-bound
   receipt. Clean incomplete prefixes continue in place; process and boundary failures retry in a
   new attempt.
8. **Full receipt verification** — compare model identity, evidence, turns, usage, extraction
   status, validity, overall score, quality, and detail metrics against durable round records, and
   verify recorded harness-request digests.
9. **Registered logical records** — accept a run record only when runner-owned state already stores
   its digest. A sibling record created by an earlier subject is ignored and independently rescored
   in a new attempt.
10. **Recoverable record commit** — retain the state-authorized record in a previous-record journal
    until state registers its replacement. A commit-window interruption rolls back to that exact
    prefix and reruns the uncommitted harness work.

## Data flow

```text
suite + baseline + public sources
  -> DeepEffectTrialRunner (fresh attempt)
  -> subject request(mode=deep_evolution, round=1..5)
  -> score exact private harness
  -> bounded previous-round feedback
  -> subject request(round+1)
  -> deep report: best + P50/P90 + round curve
```

## Module changes

- Add `famou.deep_effect_trial` with `DeepEffectTrialConfig` and `DeepEffectTrialRunner`.
- Extend `run_subject_adapter` with the score-free deep request/receipt mode while preserving the
  normal schema and prompt.
- Add `effect-deep-trial` CLI wiring and public package exports.
- Add focused fixture tests, quickstart documentation, architecture notes, and README index entry.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | No import/discovery of external Agent products. |
| Local-First and Durable State | Pass | Attempt, records, and report are local and resumable. |
| Runtime Adapter Isolation | Pass | Subject/harness remain explicit command seams. |
| Artifact-First Verification | Pass | Every round crosses the exact private evaluator. |
| Bounded Autonomy | Pass | One/two cases, 1–10 runs, bounded rounds/timeouts. |
| Honest Evidence | Pass | Descriptive comparison and explicit non-parity limitations. |

## Complexity tracking

One runner module, one adapter mode, and one CLI command. No dependency, database, service, or
population algorithm change.
