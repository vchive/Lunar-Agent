# Implementation Plan: Algorithm Problem Contract and Solver/Evaluator Workspace

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

## Summary

Add a runtime-neutral algorithm contract and validity-first evaluation report to the existing
versioned plan boundary. Contract-bearing runs create a fixed local role workspace and a hashed
manifest. The contract records `loop` (default) or `population` as a future strategy choice, but
this increment only validates and stores the choice; no candidate search is started automatically.
The same local run contract is usable directly by a person, as a JSON child process of another
Agent, or through a detached run ID that can be resumed after the caller exits.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Existing standard-library dataclasses, JSON, pathlib, hashlib, SQLite;
no new runtime or service dependency.

**Storage**: Existing SQLite plan revision document plus run-relative manifest artifact and local
directories.

**Testing**: pytest, Ruff, compileall, and CLI JSON quickstart.

**Target Platform**: Local macOS/Linux/Windows-compatible Python environment.

**Project Type**: Standalone local CLI/library.

**Performance Goals**: Contract validation under 100 ms for bounded payloads; manifest creation
does not read or copy input data.

**Constraints**: All existing limits remain in force; contract JSON ≤ 64 KiB, text/arrays/metrics
bounded, paths confined to one run workspace, no network listener.

**Scale/Scope**: One contract per plan revision; up to 64 inputs, 64 constraints, and 64 metrics;
future candidate/population scale is explicitly deferred.

## Constitution Check

| Principle | Result | Design response |
| --- | --- | --- |
| Standalone Distribution | Pass | Standard library only; no Hermes/OpenCode/Codex discovery. |
| Local-First and Durable State | Pass | Plan revision and manifest are local and recoverable. |
| Runtime Adapter Isolation | Pass | Contract validation/materialization is independent of runtime adapter. |
| Artifact-First Verification | Pass | Manifest is hashed/indexed; evaluation report has structured evidence. |
| Bounded Autonomy | Pass | Paths, text, scores, and strategy values are validated and fail closed. |
| Test-First Recovery and Small Surface | Pass | Additive model and focused fixtures preserve old plans and migrations. |

## Design decisions

1. Add one optional `algorithm_problem` field to `PlanDocument`; omitting it preserves all prior
   plan behavior.
2. Keep `AlgorithmProblemContract` and `EvaluationReport` in a small standard-library module. The
   controller only validates/materializes metadata; it does not run solver or evaluator code yet.
3. Materialize fixed directories and a manifest through a pure helper. Directories are not treated
   as successful artifacts and are not exposed as arbitrary write permissions.
4. Store a canonical digest of the contract in the manifest. The plan revision remains the source
   of truth; the manifest is an inspectable projection.
5. Define one future `EvolutionStrategy` seam with `loop` and `population` values. Loop is the
   default product path; population is opt-in and must later prove budget/diversity benefit.
6. Keep invocation mode outside the algorithm strategy: direct CLI, parent-Agent child process,
   and detached/resumed execution all use the same controller, ledger, workspace, and JSON schema.

## Project Structure

```text
src/famou/
├── algorithm.py          # contract, workspace manifest, evaluation report validation
├── policy.py             # optional PlanDocument.algorithm_problem field
├── controller.py         # validate/materialize contract-bearing run metadata
├── store.py              # persist plan JSON unchanged except additive field
└── cli.py                # expose additive plan/status JSON metadata

tests/
├── test_algorithm.py     # contract/evaluation/workspace unit and safety tests
├── test_plan.py          # legacy + algorithm plan integration regression
└── test_cli.py           # additive status/plan JSON contract
```

**Structure Decision**: Keep the existing single-project layout. Solver/evaluator implementations
are intentionally not added to `src/` in this feature; later role features will consume the
contract and workspace boundary through runtime-neutral interfaces.

## Phases

1. Add failing contract, report, and workspace tests (P1 stories 1–3).
2. Implement bounded dataclasses, canonicalization, digest, and workspace manifest.
3. Extend `PlanDocument` and controller/store integration additively; materialize only when a
   contract is present.
4. Expose plan/status JSON and preserve legacy plans, migrations, retries, and delivery.
5. Verify direct and parent-process-compatible CLI behavior, including a replan that refreshes the
   algorithm manifest without changing completed task definitions.
6. Run the full test suite, Ruff, compileall, and quickstart; update docs and commit as `vchive`.

## Complexity Tracking

No constitution violation. The optional nested contract is additive and avoids a second persistence
schema. Population, islands, migration, and service concerns remain out of scope.
