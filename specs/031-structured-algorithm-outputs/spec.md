# Feature Specification: Structured Algorithm Outputs

**Feature Branch**: `031-structured-algorithm-outputs`  
**Created**: 2026-09-03  
**Status**: Implemented  
**Input**: Algorithm missions must produce data that a user or parent Agent can consume, not only a conversational explanation.

## Context and scope

Lunar-Agent's conversational surface is useful for intake and progress, but an algorithm mission is
not complete when a model merely says that it found a solution. A mission needs a typed output
contract, independent validation, and durable delivery metadata. This feature makes output files a
first-class part of `AlgorithmProblemContract` while preserving contracts written before the field
existed.

The runtime still receives an isolated attempt workspace. A Solver writes logical paths such as
`output/routes.csv` there. After the task passes the normal evaluator and all declared output
checks, the controller atomically promotes the files to the stable run workspace at
`<run>/output/routes.csv`, hashes them, and exposes them through `status --json` and `deliver`.

## User stories and acceptance scenarios

### User Story 1 — Declare machine-consumable outputs (P1)

1. Given an algorithm contract with `outputs`, when the contract is parsed, then each output has a
   confined `output/` path, one supported format (`json`, `jsonl`, `csv`, or `text`), optional field
   names, a required flag, and an optional description.
2. Given a legacy contract without `outputs`, when it is parsed and serialized, then its canonical
   representation and behavior remain unchanged.

### User Story 2 — Reject prose-only or malformed results (P1)

1. Given a required output, when Solver returns non-empty prose without the file, then the task and
   run fail; the prose does not satisfy the output requirement.
2. Given JSON/JSONL/CSV output with invalid syntax or missing declared fields, when independent
   evaluation runs, then the task fails with bounded structured evidence.
3. Given a valid optional output, when the file exists, then it is checked and promoted; when it is
   absent, the task may still pass.

### User Story 3 — Deliver verified data (P1)

1. Given a successful run with required outputs, when `deliver` runs, then it returns a decision
   whose evidence includes the stable output paths and the ledger contains their SHA-256 records.
2. Given a successful run whose required output was never promoted, when `deliver` runs, then it
   fails closed.
3. Given a parent Agent calling `status --json`, when the run succeeds, then output artifacts are
   distinguishable by `kind=output`, with path, size, and digest metadata.

## Functional requirements

- **FR-3101**: Add an optional `outputs` array to `AlgorithmProblemContract`; each entry is bounded,
  validated, and serialized deterministically.
- **FR-3102**: Keep output paths relative and below `output/`; reject traversal, symlinked paths,
  duplicate paths, unsupported formats, duplicate fields, and credential-like text.
- **FR-3103**: Independently validate required output files after the base evaluator. JSON objects or
  arrays, JSONL objects, CSV headers, and non-empty text are supported; declared fields must exist.
- **FR-3104**: Apply the output contract to the built-in `solve`/`solver` task even when a custom
  plan omitted the generated acceptance shorthand.
- **FR-3105**: Promote only passing Solver outputs from the attempt workspace to run-level `output/`
  using confined, non-symlink paths and bounded file sizes.
- **FR-3106**: Index promoted files as `kind=output` SHA-256 artifacts and emit a bounded
  `algorithm_outputs_promoted` event.
- **FR-3107**: Make `deliver` require every required output artifact for output-bearing contracts;
  old plans retain result/runtime delivery behavior.
- **FR-3108**: Keep output paths and contents out of event payloads; ledger metadata contains paths,
  formats, fields, sizes, and digests only.

## Success criteria

- **SC-3101**: A Solver that writes `output/routes.csv` receives a stable run-level output file,
  one `output` artifact with a 64-character SHA-256 digest, and a deliver decision containing that
  path.
- **SC-3102**: A Solver that only writes a convincing textual answer cannot complete a contract with
  a required output.
- **SC-3103**: Invalid JSON/JSONL/CSV and missing fields fail independently without leaking file
  contents.
- **SC-3104**: A legacy contract without `outputs` passes the existing tests and keeps its digest
  stable.
- **SC-3105**: Full test, lint, compile, diff, and Specify prerequisite checks pass.

## Out of scope

- Streaming output, remote object stores, dataframes, binary serialization, or HTTP delivery.
- Inferring a schema from model prose; output schemas must be declared or intentionally untyped.
- Replacing the normal result/evaluation artifact; structured outputs complement the audit trail.
