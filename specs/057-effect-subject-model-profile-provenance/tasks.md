# Tasks: Effect Subject Model Profile Provenance

## Specification and tests first

- [x] T057-01 Review effect subject, normal trial, and deep trial identity/receipt boundaries.
- [x] T057-02 Add failing tests for profile CLI parsing, runtime limits, telemetry, and resume
  identity.

## Implementation

- [x] T057-03 Load and validate `ModelProfile` for `effect-subject`.
- [x] T057-04 Pass profile policy into the subject `AgentLoopRuntime` and emit score-free
  profile/usage provenance.
- [x] T057-05 Bind profile digest to normal/deep requests, receipts, trial identities, and resume
  checks.

## Verification

- [x] T057-06 Run focused/full pytest, Ruff, compileall, build, Specify prerequisites, and diff
  checks.
