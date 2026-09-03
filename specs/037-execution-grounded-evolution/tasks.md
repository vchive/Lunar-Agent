# Tasks: Execution-Grounded Conversational Evolution

## Phase 1 — tests first

- [x] T037-01 Test conversational loop/population execute every candidate and reject process/output
  failures before calling the Agent evaluator.
- [x] T037-02 Test verified staged inputs are copied to candidate and generation workspaces and
  conflicting/tampered/symlinked inputs fail closed.
- [x] T037-03 Test evaluator prompts include bounded source/execution/output metadata without raw
  input/output data or credentials.
- [x] T037-04 Test execution/output evidence is indexed and the final winner is still independently
  re-executed for parent delivery.
- [x] T037-05 Test runner fingerprint recovery plus direct evolve/OpenEvolve/source-only compatibility.

## Phase 2 — implementation

- [x] T037-06 Add `CandidateInputArtifact` and `ContractCandidateRunner` with input/output guards.
- [x] T037-07 Short-circuit execution-aware evaluation on invalid execution evidence.
- [x] T037-08 Ground Agent generation/evaluation workspaces and prompts in bounded local evidence.
- [x] T037-09 Wire and fingerprint the built-in runner for native conversational strategies.
- [x] T037-10 Index validated per-candidate outputs without promoting search-time data.

## Phase 3 — documentation and verification

- [x] T037-11 Update README and document search-time versus delivery-time execution semantics.
- [x] T037-12 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; commit
  and push as `vchive` on `main`.
