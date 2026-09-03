# Feature Specification: Private Data Profiling

**Feature Branch**: `041-private-data-profiling`
**Created**: 2026-09-03
**Status**: Implemented

## Context and scope

Feature 040 compiles, probes, and freezes one evaluator from the problem contract. Real algorithm
inputs frequently contradict or refine a declared schema: columns differ in case, nulls exist,
numeric-looking values are textual identifiers, JSON roots vary, or a supposedly unique key is not
unique. WebAgent's planning/evaluator guidance explicitly reads data before designing the judge.
Lunar-Agent currently gives its evaluator compiler only the contract, so it can still guess wrong.

This feature computes a deterministic, privacy-preserving profile of the exact digest-checked input
files and binds it into evaluator compilation and the frozen bundle. The profile exposes structural
facts—format, size, row count, actual fields, missing/unique counts, and conservative scalar types—
but no raw rows, string values, categorical samples, or source-machine paths. The profile is
persisted and hashed so resume can detect data drift before reusing evaluator authority.

## User stories and acceptance scenarios

### User Story 1 — Design evaluators from observed structure (P1)

1. Given staged CSV/JSON/JSONL/text inputs, `--compile-evaluator` builds a profile from the exact
   copied bytes before the bundle compiler runtime is invoked.
2. The compiler prompt includes declared-vs-observed fields, row counts, null/unique counts, and
   conservative type summaries, enabling generated evaluators to use actual schemas.
3. Raw record values, file contents, local source paths, and credentials never enter the profile,
   compiler prompt, manifest event, or solver refinement context.

### User Story 2 — Bind the judge to exact data (P1)

1. Each profile entry carries its run-relative path, size, and SHA-256 from the staged input ledger.
2. Bundle identity includes the canonical profile digest. Resume re-profiles the same files and
   rejects missing, changed, symlinked, malformed, or digest-mismatched inputs before scoring.
3. Profile and bundle artifacts are local, bounded, deterministic, and recoverable without a model
   call.

### User Story 3 — Fail safely on unsupported data (P1)

1. Malformed CSV/JSON/JSONL, invalid UTF-8, excessive rows/columns/nesting, duplicate headers, or a
   declared format outside the supported profile set aborts compiled-evaluator setup before search.
2. Text inputs expose only line/byte counts; arbitrary content is never interpreted or sampled.
3. Existing owner harnesses, model evaluators, ordinary solve, and low-level evolve behavior remain
   unchanged when compiled evaluation is not selected.

## Functional requirements

- **FR-4101**: Add a deterministic profiler for staged `CandidateInputArtifact` descriptors and the
  corresponding immutable `InputSpec` formats.
- **FR-4102**: Support CSV, JSON, JSONL, and text with bounded file size, rows, fields, nesting, and
  UTF-8 validation. Reject schema ambiguity rather than guessing.
- **FR-4103**: For structured formats expose only field names, row count, null count, unique count,
  and conservative type (`null`, `boolean`, `integer`, `number`, `string`, `mixed`, `object`,
  `array`). Do not expose min/max, samples, values, frequencies, or raw content.
- **FR-4104**: Validate every source path, symlink component, file size, and SHA-256 against the
  durable descriptor before parsing.
- **FR-4105**: Persist canonical `input-profile.json`, index it as an evaluator-bundle artifact, and
  include its digest in both the compiler prompt and frozen manifest/fingerprint.
- **FR-4106**: On compiled-evaluator resume, recompute and compare the profile before bundle reuse;
  no compiler runtime call occurs for unchanged evidence.
- **FR-4107**: Preserve all Feature 040 preflight/freeze restrictions and existing non-compiled
  evaluation paths.

## Success criteria

- **SC-4101**: Profiles for all four formats contain accurate structural counts/types and no fixture
  values or source-machine paths.
- **SC-4102**: The evaluator compiler fixture changes behavior based on an observed column and still
  selects/materializes the right candidate.
- **SC-4103**: Input tamper, malformed data, and profile/manifest drift fail before search or resume.
- **SC-4104**: Full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Inferring business semantics, units, time zones, sentinel meanings, or cross-table relationships
  from values; those require user confirmation or a later privacy-controlled semantic pass.
- Profiling Excel, Parquet, databases, images, binary objects, or remote URLs in this feature.
- Passing data samples to a model, even when locally hosted.
