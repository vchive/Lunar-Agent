# Feature Specification: Executable Famou-Bench Adapters

**Feature Branch**: `049-famou-bench-adapters`
**Created**: 2026-09-04
**Status**: Implemented

## Context and scope

Feature 048 established a strict, recoverable effect-trial protocol, but deliberately left the
normal Lunar subject, private Famou harness, and FM-Eval export as external commands. This feature
makes those protocol edges executable from the Lunar distribution. It does not import WebAgent or
FM-Eval service code and it does not enable an outer evolution strategy.

The built-in subject runs one fresh repository-owned Hermes-style tool session against the public
case projection. The built-in harness verifies and invokes the frozen case's actual
`extractor_agent.py` followed by its actual `evaluator.py`. The baseline converter consumes a local
FM-Eval experiment-results JSON export and produces Feature 048's strict per-run baseline. Private
harness files, credentials, and historical scores never enter the subject workspace or prompt.

## User stories and acceptance scenarios

### User Story 1 — Run Lunar itself as the normal subject (P1)

1. The effect runner invokes `lunar-agent effect-subject` with a Feature 048 request.
2. The adapter reads the public instruction and gives a fresh Agent loop access only to that
   attempt workspace, bounded local tools, and an explicitly configured OpenAI-compatible model.
3. The Agent creates concrete solution files and the adapter writes a strict score-free receipt
   containing observed model identity, turns, and provider token usage when available.
4. A malformed request, model mismatch, unsafe receipt path, runtime failure, or attempt to use
   memory/session history fails without fabricating completion.

### User Story 2 — Score through the exact private case harness (P1)

1. The effect runner invokes `lunar-agent effect-harness` with a Feature 048 harness request and an
   owner-supplied private case root.
2. The adapter recomputes the FM-Eval `case-content-v1` digest and verifies the actual
   extractor/evaluator bytes against the frozen request before running either process.
3. It runs the extractor exactly once against the subject workspace, then the evaluator exactly
   once against normalized output, and emits a strict identity-echoing receipt.
4. Extractor credentials may reach only the extractor child. The evaluator receives a minimal
   credential-free environment. Raw stdout, stderr, secrets, and private paths are not persisted in
   the receipt.

### User Story 3 — Convert an FM-Eval results export without typing a target score (P1)

1. An owner saves the authorized FM-Eval experiment results response locally and supplies the
   matching frozen suite plus model identity.
2. Lunar selects only suite cases, normalizes zero/one-based run indexes and extraction vocabulary,
   and copies only per-run readiness, validity, and overall score.
3. Missing cases, duplicate run indexes, malformed scores, an experiment mismatch, or an existing
   output fails closed.
4. No best score is accepted or emitted; Feature 048 derives it from converted runs.

## Functional requirements

- **FR-4901**: Add separate `effect-subject`, `effect-harness`, and `effect-baseline` CLI/library
  surfaces that implement Feature 048 contracts without entering Lunar evolution.
- **FR-4902**: The subject MUST use one stateless attempt-local Agent session. It MUST NOT read
  durable memory, prior transcripts, baseline data, private harness material, or machine-wide
  Hermes/OpenCode/Codex state.
- **FR-4903**: The subject prompt MUST bind the public entrypoint, concrete-data-output objective,
  workspace boundary, and score-free role. Local command execution is explicit and bounded.
- **FR-4904**: The OpenAI-compatible runtime MUST preserve response model identity and valid
  prompt/completion/total token usage across all Agent turns. Missing usage MUST remain unavailable,
  not be represented as measured zero.
- **FR-4905**: The harness MUST verify non-symlink extractor/evaluator files against the request's
  SHA-256 values, independently recompute the private case content digest and public projection,
  and MUST execute extractor then evaluator once each using explicit Python.
- **FR-4906**: The harness MUST give the evaluator a fresh minimal environment without extractor,
  model, proxy, BOS, or arbitrary parent credentials. Process diagnostics MUST remain ephemeral.
- **FR-4907**: Extractor failure/partial output MUST yield an honest invalid receipt and skip the
  evaluator. Evaluator failure MUST yield an invalid receipt. Successful scores MUST be finite and
  validity MUST be in `[0,1]`.
- **FR-4908**: The baseline converter MUST accept local JSON only, support legacy
  `{meta,results}` and current `{experiment,results}` projections, select suite cases, and produce
  the exact Feature 048 baseline schema.
- **FR-4909**: The converter MUST never accept a manual best score, fetch service credentials,
  mutate FM-Eval, infer immutable suite identities from a mutable branch, or overwrite an existing
  output by default.
- **FR-4910**: Requests, receipts, outputs, and case script paths MUST be bounded, non-symlinked,
  and confined to their declared roots. JSON writes MUST be atomic.
- **FR-4911**: Existing generic runtimes, agent loop callers, effect trials, and service-free core
  behavior MUST remain backward compatible.

## Success criteria

- **SC-4901**: A fake OpenAI-compatible server drives the built-in subject through at least one
  tool call, creates a solution artifact, and produces a strict receipt with aggregated telemetry.
- **SC-4902**: A deterministic fake case proves extractor-to-evaluator ordering, exact script
  digest verification, score mapping, and evaluator credential isolation.
- **SC-4903**: A representative FM-Eval results fixture converts into per-run baseline data that
  Feature 048 accepts and from which it derives the historical best.
- **SC-4904**: The three built-in adapters complete a deterministic end-to-end effect trial without
  hand-written wrapper scripts.
- **SC-4905**: Focused/full tests, lint, compileall, deterministic quickstart, diff inspection, and
  Specify checks pass.

## Out of scope

- Downloading private benchmark publications or FM-Eval results over the network.
- Bundling Famou case files, extractor dependencies, credentials, or a historical `1.10.6` release.
- Replacing the official extractor with Lunar heuristics or reimplementing case evaluators.
- Comparing WebAgent `/evolve`; this remains a later matched five-outer-iteration experiment.
- Providing an OS sandbox. Same-user hostile subprocesses still require owner-provided isolation.
