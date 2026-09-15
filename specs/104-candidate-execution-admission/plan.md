# Plan

1. Freeze a path-free execution-admission schema, canonical digest, bounds, and fixed errors.
2. Add immutable DTOs for input descriptors, evaluator identity, and physical execution budget;
   deeply reconstruct all nested values on parse and validation.
3. Reuse the Feature 103 plan validator and shared descriptor reader for optional input-byte
   verification. Check caller pins before opening any input file.
4. Add a static CLI admission command dispatched before normal configuration/Store initialization;
   emit only identity, counts, sizes, and status.
5. Add offline tests for canonical replay, all pin mismatches, duplicate/path-unsafe inputs,
   source replacement, bounds, no side effects, and absence of execution/import/evaluator calls.
6. Update README, architecture, roadmap, and handoff only after implementation and full regression.

## Decisions

The admission is separate from workspace materialization so a materialized directory can be owned
and cleaned by a later runner without changing its identity. Inputs are logical targets plus caller
labels rather than absolute paths; a future staging feature decides how verified bytes enter the
workspace. Dependency and environment values are commitments, not host inspection shortcuts.

The exact evaluator remains an explicit pin. An external framework's score, generation, checkpoint,
or task ID cannot satisfy this contract or become Lunar score/rank/iteration authority.

## Complexity tracking

No database migration, Candidate mutation, archive change, runner adapter, package installation,
network call, or model/provider dependency is introduced. Byte checks are bounded per descriptor
and do not claim an atomic multi-file snapshot.
