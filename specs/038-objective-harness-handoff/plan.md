# Implementation Plan: Objective Harness Handoff

**Branch**: `main` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

## Technical context

Feature 037 already guarantees that the downstream evaluator runs only after candidate execution
and output validation. `CommandCandidateEvaluator` already implements the candidate-path protocol,
timeout/output bounds, and strict report parsing for low-level `evolve`. The change exposes that
existing seam through the conversational request, adds a minimal-environment option, and includes
the evaluator profile in durable resume validation.

## Decisions

1. **One evaluation schema** — harnesses return `EvaluationReport`; validity, quality, detailed
   metrics, and archive ranking retain their current meaning.
2. **Execution remains the first gate** — the existing `ExecutionAwareCandidateEvaluator` wraps
   the harness, so missing/malformed output never invokes the objective program.
3. **Higher-is-better archive score** — domain harnesses normalize minimization objectives into
   `combined_score`; Lunar-Agent does not guess scaling from prose.
4. **Explicit local authority** — the command is opt-in and no global executable is discovered.
5. **Fingerprint, not command persistence** — state/events retain only SHA-256 identity and a
   configured flag. Resume and post-clarification continuation require the caller to resupply it.
6. **Minimal evaluator environment** — conversational harnesses receive deterministic UTF-8/locale
   settings and no inherited model credentials. Direct low-level callers keep current inheritance
   unless they explicitly construct an evaluator with an environment.

## Data flow

```text
runtime solver -> candidate.py
                    |
                    v
       ContractCandidateRunner
       data/raw + output + execution
                    |
          failure --+--> validity=0
                    |
                    v
       explicit objective harness
       strict EvaluationReport
                    |
                    v
       archive selection -> clean-room final materialization
```

## Recovery and safety

- CLI validation happens before a new conversational run is created.
- The persisted request records `evaluator_command_configured=true`, never the command text.
- Strategy state binds the hashed command profile and rejects command drift before execution.
- Compiler answers do not attempt to reconstruct an absent command; the run remains resumable with
  `solve --resume --evaluator-command ...`.
- Harness subprocess stdin is closed, output is bounded, timeout is enforced, and report parsing is
  fail-closed.

## Constitution check

| Principle | Result | Design response |
|---|---|---|
| Standalone Distribution | Pass | Explicit command is optional; repository defaults remain usable. |
| Local-First and Durable State | Pass | Parent/child ledger, archive, and resume remain authoritative. |
| Runtime Adapter Isolation | Pass | Reuses the injected evaluator protocol. |
| Artifact-First Verification | Pass | Harness reads executed candidate artifacts before selection. |
| Bounded Autonomy | Pass | Explicit command, minimal environment, timeout, output cap. |
| Test-First Recovery | Pass | Wrong-score, failure, detach, answer, and drift cases precede code. |

## Complexity tracking

No dependency, database migration, service, or new process protocol is added. This feature does not
claim to derive objective functions; it makes an owner-supplied exact oracle a first-class peer of
the Agent evaluator on the high-level path.
