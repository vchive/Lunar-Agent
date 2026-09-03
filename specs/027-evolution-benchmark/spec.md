# Feature Specification: Reproducible Evolution Benchmark

**Feature Branch**: `027-evolution-benchmark`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Compare local evolution strategies under the same algorithm contract and budget

## Context and scope

Lunar-Agent now has runtime-neutral `loop`, `population`, and optional `openevolve` seams. The
project needs a local benchmark harness before claiming effect parity with WebAgent: one contract,
one generator/evaluator definition, and one budget must be applied to independently isolated runs.
The first release compares native strategies through the existing `EvolutionContext`; external
OpenEvolve and remote model endpoints remain explicit adapters and are not discovered implicitly.

The benchmark is an analysis tool, not a second scheduler. It writes a bounded JSON report and
per-strategy workspaces, while each strategy keeps its normal append-only archive and validity-first
selection semantics.

## User stories and acceptance scenarios

### User Story 1 — Compare strategies on identical inputs (P1)

1. Given an algorithm contract and explicit generator/evaluator commands, when `benchmark` runs,
   then each selected strategy receives the same canonical contract and equivalent evolution budget.
2. Every strategy executes in a separate workspace and cannot read another strategy's archive.

### User Story 2 — Produce machine-readable evidence (P1)

1. The benchmark report contains status, elapsed time, evaluated/valid candidate counts, best score,
   and relative artifact paths for every strategy.
2. A failed strategy is recorded as a bounded failure entry; it does not prevent other strategies
   from completing and does not produce a false best candidate.

### User Story 3 — Keep comparisons reproducible and local (P1)

1. The report records contract digest, benchmark configuration, and generator/evaluator identities
   as credential-safe fingerprints.
2. Re-running with the same seed and inputs uses a fresh benchmark directory and never mutates an
   existing run.

## Functional requirements

- **FR-2701**: Provide a library `BenchmarkRunner` that runs selected native strategies through the
  existing `EvolutionContext` seam.
- **FR-2702**: Require a generator/evaluator factory or explicit adapters for every benchmark case;
  no PATH discovery or machine-wide agent state is allowed.
- **FR-2703**: Give every strategy an isolated workspace and bounded `EvolutionConfig`; preserve
  all existing candidate/evaluator validation and cancellation behavior.
- **FR-2704**: Emit a bounded JSON-safe `BenchmarkReport` with per-strategy metrics and errors.
- **FR-2705**: Add a CLI command that accepts one contract, selected native strategies, explicit
  generator/evaluator commands, and common budget options.
- **FR-2706**: A benchmark must fail closed on invalid strategy names, empty selections, invalid
  budgets, contract mismatch, or unsafe workspace paths.
- **FR-2707**: The first CLI version compares `loop` and `population`; `openevolve` remains
  separately invocable until its external process contract is normalized for fair measurement.

## Success criteria

- **SC-2701**: A deterministic fixture produces a report containing both `loop` and `population`
  with isolated archives and comparable budgets.
- **SC-2702**: A failing generator/evaluator is represented in one strategy entry while another
  selected strategy still produces a valid report.
- **SC-2703**: Report and state contain no raw API keys, command output, or absolute paths where a
  relative path is sufficient.
- **SC-2704**: Existing full tests and all legacy CLI commands remain green.

## Out of scope

- Statistical significance claims, distributed workers, HTTP/SSE services, or automatic model
  discovery.
- Changing strategy ranking, evaluator authority, or candidate archive formats.
- Treating scheduler `--workers` as population size.
