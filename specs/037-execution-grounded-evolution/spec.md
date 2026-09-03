# Feature Specification: Execution-Grounded Conversational Evolution

**Feature Branch**: `037-execution-grounded-evolution`
**Created**: 2026-09-03
**Status**: Implemented

## Context and scope

Feature 036 executes and validates the selected winner before delivery. Native conversational
`loop` and `population` search still select candidates before that point using an Agent evaluator
that is given a local source path. An OpenAI-compatible one-shot model cannot read that path, and a
candidate that does not run or produce its required output may consume evaluator calls and enter
the archive with a model-reported score. This weakens both search efficiency and evidence quality.

This feature makes every native `solve --evolve` candidate execution-grounded. Before the
independent evaluator is called, Lunar-Agent copies verified `data/raw/*` inputs into that
candidate's private directory, runs self-contained Python source with the same bounded local
protocol as final materialization, and checks required/present outputs against `OutputSpec`.
Process or output failure becomes an immediate validity-zero report and does not call the model
evaluator. Successful candidates give the evaluator a bounded source excerpt, canonical execution
summary, and output metadata. Final winner materialization remains a separate clean-room run.

## User stories and acceptance scenarios

### User Story 1 — Search only over executable candidates (P1)

1. Given native conversational loop/population search, every generated candidate is invoked in its
   own archive directory with copied verified inputs before independent scoring.
2. A non-zero exit, timeout, malformed required output, missing field, symlink, path violation, or
   oversized output produces `validity=0` and `combined_score=0`; the independent Agent evaluator
   is not called for that candidate.
3. A passing candidate retains bounded `execution.json`, verified candidate output artifacts, and
   can enter validity-first selection.

### User Story 2 — Ground evaluator decisions in readable evidence (P1)

1. The Agent evaluator request includes a bounded candidate source excerpt rather than only an
   inaccessible filesystem path.
2. When execution evidence exists, the request includes status, exit code, duration, errors, and
   verified output path/format/fields/size/SHA-256 metadata, but not raw input or output contents.
3. Solver generation workspaces receive verified input copies at `data/raw/*`, allowing an explicit
   local subprocess or tool-loop Agent to inspect the same data the candidate will execute against.

### User Story 3 — Preserve recovery and adapter boundaries (P1)

1. The built-in search runner has a credential-safe fingerprint derived from protocol version,
   interpreter identity, contract digest, and input digests; resume rejects changed evidence.
2. Search-time outputs never become parent deliverables. The selected candidate is re-executed by
   Feature 036 before promotion.
3. Direct `evolve` keeps its explicit optional runner contract, OpenEvolve remains an external
   strategy, and source-only contracts remain compatible while gaining a syntax/process check.

## Functional requirements

- **FR-3701**: Add a runtime-neutral `ContractCandidateRunner` that composes the existing process
  runner with verified input staging and exact output-contract validation.
- **FR-3702**: Validate input path, size, SHA-256, source confinement, destination confinement, and
  symlink components before copying. Identical retries are idempotent; different bytes fail closed.
- **FR-3703**: Execute candidates without a shell using the absolute current Python interpreter,
  isolated mode, bounded timeout/output, and a minimal non-secret environment.
- **FR-3704**: Validate required outputs and present optional outputs using the existing
  `output_valid` interpreter; only validated contract outputs may be declared as execution
  artifacts.
- **FR-3705**: Change the execution-aware evaluator to short-circuit on runner failure and return a
  strict local invalid report without invoking the downstream evaluator.
- **FR-3706**: Apply this runner automatically to conversational native loop/population strategies,
  persist its fingerprint in strategy state, and index per-candidate execution/output evidence.
- **FR-3707**: Stage bounded verified contract inputs into Agent generation workspaces without
  exposing source-machine paths or overwriting different bytes.
- **FR-3708**: Ground Agent evaluator prompts with bounded UTF-8 candidate source, process evidence,
  and verified output metadata; exclude raw data contents, credentials, and unbounded stderr.
- **FR-3709**: Preserve final clean-room materialization, direct explicit runner commands,
  OpenEvolve, detached execution, resume, and all existing APIs when this automatic path does not
  apply.

## Success criteria

- **SC-3701**: A two-round conversational fixture generates an invalid high-claim candidate then a
  valid lower-claim candidate; only the valid candidate reaches the model evaluator and becomes
  best/deliverable.
- **SC-3702**: Every native conversational candidate has bounded execution evidence; valid outputs
  are indexed while invalid outputs never become parent `kind=output` artifacts.
- **SC-3703**: Evaluator prompts contain source/execution/output metadata but not raw staged rows or
  credential environment values.
- **SC-3704**: Resume retains the same runner fingerprint and archive; input/candidate evidence
  tampering fails closed.
- **SC-3705**: Full tests, lint, compile, diff, quickstart, and Specify checks pass.

## Out of scope

- Deriving a mathematically exact domain objective function from arbitrary natural language.
- Sending raw local datasets or full generated outputs to a remote model automatically.
- Changing OpenEvolve's internal population execution, installing dependencies, arbitrary
  candidate languages, containers, or hard operating-system resource isolation.
