# Tasks: Execution-Grounded Refinement

## Phase 1 — tests first

- [x] T039-01 Test a second loop prompt contains prior bounded source, concrete execution failure,
  and evaluator feedback, then produces a valid repaired candidate.
- [x] T039-02 Test raw input/output contents, credentials, and adapter exception details never enter
  refinement prompts.
- [x] T039-03 Test verified output path/size/SHA-256 metadata appears without output contents.
- [x] T039-04 Test missing, malformed, oversized, escaped, and symlinked evidence degrades safely.
- [x] T039-05 Test population parent/inspiration and resumed archive prompts use the same envelope.
- [x] T039-06 Test direct callback and command generators retain their existing request contract.

## Phase 2 — implementation

- [x] T039-07 Add safe source/execution/output evidence projectors with field and item bounds.
- [x] T039-08 Use the shared projector for Agent parent, inspiration, and archive summaries.
- [x] T039-09 Preserve total prompt bounds, credential redaction, and generic evaluator failure text.

## Phase 3 — documentation and verification

- [x] T039-10 Update README architecture/evolution guidance with evidence-grounded refinement.
- [x] T039-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; mark
  implemented, commit, and push as `vchive` on `main`.
