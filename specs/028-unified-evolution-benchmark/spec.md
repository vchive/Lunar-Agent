# Feature Specification: Unified Evolution Benchmark Adapters

**Feature Branch**: `028-unified-evolution-benchmark`
**Created**: 2026-09-03
**Status**: Implemented
**Input**: Include the explicit OpenEvolve adapter in the local strategy benchmark

## Context and scope

Feature 027 compares native `loop` and `population` strategies under one bounded contract and
budget. OpenEvolve remains separately invocable even though Lunar-Agent already has a strict
subprocess/result adapter. This feature makes that adapter a third benchmark strategy without
introducing package discovery, a service layer, or a second archive format.

OpenEvolve receives the same canonical contract and common budget projection as native strategies.
Its executable remains explicit and its result is imported through the existing validity-first
`OpenEvolveStrategy` path. A malformed, missing, escaping, or invalid external result is recorded
as a failed strategy entry while other benchmark strategies continue.

## User stories and acceptance scenarios

### User Story 1 — Compare OpenEvolve with native strategies (P1)

1. Given `--strategy openevolve --openevolve-command /absolute/executable`, when `benchmark`
   runs, then OpenEvolve gets an isolated workspace and the same contract/budget projection.
2. A benchmark may select any ordered subset of `loop`, `population`, and `openevolve`.

### User Story 2 — Preserve explicit process and result authority (P1)

1. OpenEvolve is never discovered from PATH or imported as a Python dependency.
2. Only the existing `result.json` candidate/evaluation envelope can enter the canonical archive;
   stdout prose or an exit-success claim cannot create a valid candidate.

### User Story 3 — Keep reports comparable and safe (P1)

1. The report records the OpenEvolve command as a credential-safe fingerprint and exposes only
   relative workspace/archive/candidate paths.
2. One adapter failure does not suppress completed results from other strategies.

## Functional requirements

- **FR-2801**: Extend benchmark strategy selection to `loop`, `population`, and `openevolve`.
- **FR-2802**: Require an explicit executable for every selected `openevolve` strategy.
- **FR-2803**: Project common rounds, stagnation, population, migration, seed, and timeout values
  into the OpenEvolve config envelope without changing the native strategy archive contract.
- **FR-2804**: Persist only SHA-256 command fingerprints in benchmark state/report.
- **FR-2805**: Keep per-strategy workspace isolation and partial-failure reporting.
- **FR-2806**: Preserve the existing OpenEvolve path, candidate confinement, schema validation, and
  evaluator authority.

## Success criteria

- **SC-2801**: A deterministic OpenEvolve fixture and native fixtures appear as three report entries
  with isolated archives and comparable budget fields.
- **SC-2802**: Invalid OpenEvolve command/result is reported as `failed`; native entries still run.
- **SC-2803**: Raw OpenEvolve command, stdout, credentials, and absolute candidate paths are absent
  from the persisted benchmark report/state.
- **SC-2804**: Existing tests and Feature 027 behavior remain unchanged for the default two-strategy
  benchmark.

## Out of scope

- Installing or importing OpenEvolve, automatic executable discovery, remote execution, or process
  pools.
- Claiming statistical equivalence between strategies from one benchmark run.
- Runtime-backed model loop options; those remain explicit factories for library callers and a
  follow-up CLI feature.
