# Tasks

- [x] T001 Freeze the candidate-generation budget and diagnostic contract, including authority
      identity, outcome vocabulary, bounded fields, and compatibility/non-goals.
- [x] T002 Trace native and bundle generation call sites and add an immutable explicit candidate
      budget boundary without changing deterministic or command generators.
- [x] T003 Carry the effective budget identity and candidate scope through `AgentRequest` and the
      existing runtime advisory/observer path without mutating replayable messages or transcripts.
- [x] T004 Preserve atomic `AgentStepLimitReached` admission and add bounded typed diagnostics for
      tool-step rejection, tool failure, timeout, cancellation, empty final response, malformed
      candidate, and generic worker failure.
- [x] T005 Gate `completed` on nonempty tool-free parser-accepted candidate text; prove that
      rejected/incomplete generations cannot publish candidates or begin execution/evaluation.
- [x] T006 Add offline fixture tests for success, `4 + 2` rejection, each diagnostic outcome,
      identity mismatch/tampering, advisory/transcript immutability, and no-retry semantics.
- [x] T007 Run focused/shared regressions, Ruff, compileall, Specify checks, link and diff checks;
      independently inventory Feature 134 bytes and hashes.
- [x] T008 Perform independent review, update `HANDOFF.md` and readiness/roadmap notes, mark this
      SDD complete, commit and push the verified feature. Do not start a real campaign until a
      fresh registration is reviewed.
