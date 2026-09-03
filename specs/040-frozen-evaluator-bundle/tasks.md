# Tasks: Frozen Evaluator Bundle

## Phase 1 — tests first

- [x] T040-01 Test strict bundle compilation, constraint counterexamples, score ordering, and real
  candidate evaluation.
- [x] T040-02 Test unsafe imports/dynamic execution, malformed envelopes/reports, invalid paths,
  missing coverage, wrong validity, and reversed scores fail before bundle promotion.
- [x] T040-03 Test bundle files are hashed, read-only, indexed, hidden from solver workspaces, and
  loaded without recompilation on resume.
- [x] T040-04 Test tampered, symlinked, writable, missing, and contract-mismatched bundles fail.
- [x] T040-05 Test solve/detach/answer option validation and explicit evaluator compatibility.

## Phase 2 — implementation

- [x] T040-06 Implement the strict bundle/probe data model and safe source validator.
- [x] T040-07 Implement compiler prompt, staging, probe execution, atomic freeze, and loader.
- [x] T040-08 Add a digest-verifying `CandidateEvaluator` adapter around the frozen source.
- [x] T040-09 Integrate compiled bundles into conversational CLI persistence, fingerprints, artifact
  indexing, detach/answer recovery, and execution-grounded evaluation.

## Phase 3 — documentation and verification

- [x] T040-10 Update README with frozen-evaluator authority, limits, and CLI examples.
- [x] T040-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; mark
  implemented, commit, and push as `vchive` on `main`.
