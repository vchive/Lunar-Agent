# Feature Specification: Matched Deep-Evolution Effect Trial

**Feature Branch**: `main`  
**Created**: 2026-09-05  
**Status**: Implemented

## Context and scope

Feature 048/049 can measure a frozen normal-Agent run, but normal runs do not exercise the outer
evolution loop that WebAgent exposes through `/evolve`. The checked-in WebAgent source uses five
outer rounds when no argument is supplied. This feature adds a local, bounded protocol for measuring
that effect layer without importing WebAgent, FM-Eval, Hermes, OpenCode, or a service runtime.

The protocol uses the same one/two-case frozen suite and exact private harness as the normal trial.
Each logical run owns one attempt workspace and executes five fresh subject invocations. A subject
invocation may inspect artifacts from earlier rounds and receives only the previous round's bounded
harness feedback. The harness scores every round, so the report can show round-by-round improvement
as well as the best result reached by the run.

## User stories and acceptance scenarios

### User Story 1 — Run a source-aligned five-round evolution trial (P1)

1. The owner supplies the existing frozen suite, imported per-run baseline, public case sources,
   explicit subject and harness commands, model identity, and a run count.
2. Lunar defaults to five outer rounds, creates a fresh attempt per logical run, and invokes the
   subject once per round in the same attempt workspace.
3. After each round, Lunar invokes the exact private extractor/evaluator and stores the bounded
   validity, quality, score, and model telemetry. Round two onward receives only the previous
   bounded `RoundFeedback` projection, never private harness files or historical baseline rows.
4. The final report distinguishes deep evolution from the normal baseline and includes the best
   score, P50/P90 distributions, and a per-round gain curve.

### User Story 2 — Recover an interrupted expensive deep run (P1)

1. State freezes suite, baseline, command, model, run count, timeout, and outer-round settings
   before execution.
2. `--resume` reuses verified completed logical records. Only an `incomplete_rounds` record may
   continue its existing attempt; process or boundary failures restart the logical run in a new
   attempt while preserving prior attempt evidence.
3. A completed subject receipt for an unrecorded round may be reused only when its request SHA-256
   matches the reconstructed request. An unrecorded harness result is discarded and the exact
   private harness is invoked again.
4. Changed control/public identities, receipt telemetry or scores, recorded harness requests, round
   identities, or configuration fail closed.

### User Story 3 — Make an honest WebAgent comparison (P1)

1. The report records `outer_rounds=5`, `strategy=loop`, and the source-default alignment explicitly.
2. A deep run marks a descriptive breakthrough only when its evaluator-valid best score is strictly
   greater than the imported historical normal-run best for the same frozen case.
3. The report never claims WebAgent implementation identity, suite parity, statistical superiority,
   or formal benchmark publication from this small trial.

## Functional requirements

- **FR-5101**: Add a separate `effect-deep-trial` library/CLI surface; existing `effect-trial`
  scoring and report schemas remain unchanged. Both protocols MUST reject unregistered logical-run
  records and rescore them through a new attempt.
- **FR-5102**: Accept exactly one or two frozen suite cases and 1–10 logical runs per case. The
  default outer-round count MUST be five; all values MUST be frozen in state identity.
- **FR-5103**: Invoke an explicit subject command once per outer round in one attempt workspace. The
  subject request MUST identify mode, run, round, total rounds, public ledger, and receipt path. The
  subject MUST NOT create or modify a sibling private-harness workspace.
- **FR-5104**: The subject receipt MUST be score-free and identify the requested/effective model,
  provider evidence, turns, and optional token usage for that round. Built-in deep receipts MUST
  include `request_sha256` over the canonical request. Legacy completed receipts remain readable,
  but an unrecorded subject round cannot be reused without this binding.
- **FR-5105**: Invoke the existing exact harness after every round. A round's score is accepted only
  from the private harness; incomplete extraction is invalid and does not become a best score. A
  harness result becomes reusable only after its round is in the durable logical record; an
  unrecorded result MUST be discarded and rescored.
- **FR-5106**: Persist each bounded logical-run prefix with atomic file replacement and a
  previous-record journal that covers the record/state commit window. Resumption MUST be idempotent
  and MUST verify all control/public identities before continuing.
  Before accepting recorded rounds, it MUST re-read and compare every subject model/usage field and
  harness score/detail field, verify recorded harness-request digests, and reject unsafe artifact
  directories. A logical record without a digest already registered in runner-owned state MUST be
  rescored in a new attempt rather than adopted.
  Legacy completed records MAY remain readable, but the report and documentation MUST NOT claim
  that the new integrity checks retroactively establish their pre-upgrade provenance.
- **FR-5107**: Report per-case best and delta, valid/ready rates, P50/P90 score/validity/quality,
  round-best and round-P50/P90 curves, model identity matching, and explicit limitations.
- **FR-5108**: Persist no absolute source paths, commands, credentials, private files, raw process
  output, baseline rows, or secret values in subject requests, receipts, state, or report.
- **FR-5109**: Subprocess boundaries are capability/input boundaries, not an OS sandbox; document
  that hostile same-user commands require owner-provided isolation.

## Success criteria

- **SC-5101**: A deterministic fixture completes a two-run, five-round deep trial, records ten
  harness scores, and reports the expected per-round curve, including regressions.
- **SC-5102**: A fixture with round scores `[0.40, 0.55, 0.55, 0.60, 0.58]` reports best `0.60`,
  correct P50/P90, and gain `0.20` from first to best.
- **SC-5103**: Subject score fabrication, changed public bytes, receipt tampering, harness drift,
  missing rounds, resume identity changes, preseeded sibling harness workspaces, changed request
  digests, unregistered future-run records, and tampering with model evidence, usage, validity,
  quality, or detail metrics fail closed without inventing a score.
- **SC-5103a**: Interruption after replacing a later-round record but before registering its new
  state digest restores the prior state-authorized prefix and independently reruns the uncommitted
  harness evaluation.
- **SC-5104**: Existing normal effect-trial tests and all repository tests remain green.
- **SC-5105**: Focused/full tests, lint, compileall, quickstart, Specify checks, and diff review pass.

## Out of scope

- Running the complete 20-case Famou suite or publishing FM-Eval experiments.
- Claiming that five local rounds reproduce every WebAgent role, prompt, model call, or service detail.
- Implementing reinforcement learning, learned selection, or a second population protocol in this
  effect-measurement feature.
