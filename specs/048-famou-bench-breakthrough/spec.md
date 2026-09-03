# Feature Specification: Frozen Famou-Bench Breakthrough Trial

**Feature Branch**: `048-famou-bench-breakthrough`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

The available WebAgent experiment is a normal Agent run on `famou-bench 1.10.6`: 20 cases with
three runs per case and deep evolution disabled. Its roughly 50 Agent interactions per run are
ordinary model/tool turns, not evolution generations. WebAgent deep evolution is a separate,
explicit outer loop; the checked-in `init_evolution` tool defaults to five iterations when `/evolve`
has no numeric argument, but no comparable evaluated deep-evolution baseline is currently
available.

Running all 60 trials is too expensive for Lunar's first effect check. This feature therefore adds
a bounded local trial for one or two frozen `famou-bench 1.10.6` cases. Each selected case is run
repeatedly in normal, non-evolution Lunar mode and scored through an explicit adapter to the exact
Famou extractor/evaluator harness. A separately exported FM-Eval baseline supplies the historical
WebAgent runs. Lunar reports whether any evaluator-valid Lunar run strictly exceeds that case's
historical WebAgent best score. This is a user-defined single-case breakthrough milestone, not
suite parity, statistical superiority, or evidence about deep evolution.

## User stories and acceptance scenarios

### User Story 1 — Freeze a small official benchmark slice (P1)

1. An owner supplies a suite manifest for one or two cases with the benchmark publication,
   evaluation profile, case revision/digest, public-file ledger, and extractor/evaluator digests.
2. The owner maps each case to a local source directory. Lunar copies only ledger-listed public
   files into a fresh subject workspace and verifies every byte, size, path, and digest.
3. A changed, missing, symlinked, escaping, duplicate, unlisted entrypoint, or known private harness
   path fails before the subject runs.

### User Story 2 — Repeat ordinary Lunar Agent runs and use the official score boundary (P1)

1. The owner supplies explicit subject and harness commands, separate environment allowlists, a
   requested model, run count, and timeout.
2. Every logical run gets a fresh attempt workspace. Lunar places only the public case projection
   and requested model in the subject request/tree; it does not place baseline scores, private
   harness config, or harness credentials there.
3. The harness receives the completed subject workspace and must return a strict receipt matching
   the frozen benchmark, case, evaluation profile, extractor, and evaluator identities.
4. Lunar records external duration plus bounded model/turn/token telemetry when the subject can
   provide it; telemetry never substitutes for a harness score.

### User Story 3 — Report a breakthrough without overclaiming (P1)

1. Lunar validates that the imported baseline covers the same benchmark publication, selected case
   revisions/digests, evaluation profile, and exact harness identities.
2. For each case, Lunar compares the best evaluator-valid score on each side and marks breakthrough
   only when `lunar_best > webagent_historical_best`.
3. The report separately states descriptive comparability, formal conclusion eligibility, model
   evidence, run coverage, and the limitations that one/two selected cases cannot establish suite
   parity and normal-mode evidence says nothing about deep evolution.
4. A failed trial remains visible and makes coverage incomplete without erasing other trials or an
   independently valid score.

### User Story 4 — Recover an interrupted expensive run (P1)

1. Lunar freezes a state identity before the first subject process starts and atomically records
   each completed logical run.
2. `--resume` verifies all suite, baseline, command, model, run-count, timeout, and public-source
   identities, reuses completed records, and creates a new attempt directory for only an
   interrupted logical run.
3. A changed configuration, receipt, staged source, or completed record fails closed.

## Functional requirements

- **FR-4801**: Add a separate `effect-trial` library/CLI surface. It MUST NOT invoke Lunar `loop`,
  `population`, OpenEvolve, or WebAgent `/evolve`.
- **FR-4802**: Accept exactly one or two cases and a bounded 1–10 runs per case; defaults MAY be
  provided by the CLI but all effective values MUST be frozen in local state.
- **FR-4803**: Validate the suite manifest's benchmark name/release/publication digest, evaluation
  profile, case revision/digest, public-file size/SHA-256 ledger, entrypoint, and harness digests.
- **FR-4804**: Stage only verified public files. Known private paths such as `gt.json`, `tests/`,
  `.harness/`, evaluator, and extractor sources MUST be rejected from the subject ledger.
- **FR-4805**: Invoke only explicit absolute subject/harness executables. Commands receive one
  generated config path, closed stdin, bounded time/output, and separately allowlisted environment
  variables; raw commands, values, stdout, and stderr MUST NOT enter the report.
- **FR-4805a**: Treat subprocess separation as a capability/input boundary, not an OS sandbox. Recheck
  frozen controls, public sources, staged bytes, and prior records after execution; document that a
  hostile same-user process requires an owner-provided sandbox.
- **FR-4806**: Require the subject receipt to describe completion, requested/effective model,
  provider-proof level, interaction turns, and token usage using bounded typed fields.
- **FR-4807**: Require the harness receipt to echo all frozen case/harness identities and contain
  extraction status, validity, overall score, and optional quality/detail metrics. Lunar MUST never
  accept a subject-authored score.
- **FR-4808**: Import a baseline export containing per-run WebAgent receipts rather than a manually
  entered best number, validate all shared identities, and derive the historical best locally.
- **FR-4809**: Write a path-safe report containing per-run readiness/validity/score/telemetry,
  per-case coverage and aggregates, strict score deltas, milestone state, model evidence,
  descriptive comparability, the baseline's inherited eligibility state, this small trial's fixed
  formal ineligibility, and explicit limitations.
- **FR-4810**: Persist immutable state and atomic per-run records. Resume MUST be idempotent for
  completed runs and preserve incomplete attempt directories as recovery evidence.
- **FR-4811**: Keep the existing strategy benchmark, evolution engines, evaluator bundle, SQLite
  task state, runtime adapters, base dependencies, and service-free local default unchanged.

## Success criteria

- **SC-4801**: A deterministic two-case fixture stages exact public bytes and completes three fresh
  ordinary runs per case through one strict harness identity.
- **SC-4802**: When a valid Lunar score is `0.81` and the matching baseline's derived best is
  `0.80`, the report marks that case and the user-defined milestone achieved with delta `0.01`.
- **SC-4803**: Equality, invalid Lunar output, a subject-authored score, harness identity mismatch,
  changed public bytes, private-file exposure, and incomplete run coverage cannot fabricate a
  controlled breakthrough conclusion.
- **SC-4804**: Killing after one recorded run and resuming executes only unfinished logical runs;
  changing any frozen identity is rejected.
- **SC-4805**: Persisted state/report contain no secret values, raw commands, process output,
  absolute source paths, baseline data in subject config, or private harness config in the subject
  tree.
- **SC-4806**: Focused/full tests, lint, compile, deterministic quickstart, diff inspection, and
  Specify checks pass.

## Out of scope

- Running all 20 cases or reproducing the existing 60-run experiment in this feature.
- Claiming overall WebAgent parity, model-independent superiority, or a statistically powered
  conclusion from best-of-N on one or two selected cases.
- Comparing deep evolution. A later feature must first produce matched WebAgent and Lunar outer-loop
  baselines; WebAgent's source-default iteration budget is five.
- Bundling Famou's private case material, FM-Eval service code, credentials, OpenCode, or WebAgent.
- Publishing experiments or mutating the FM-Eval service.
