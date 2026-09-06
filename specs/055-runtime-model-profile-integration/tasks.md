# Tasks: Runtime Model Profile Integration

## Specification and tests first

- [x] T055-01 Review runtime loop, profile, and usage telemetry seams.
- [x] T055-02 Add failing tests for profile budget rejection, cost telemetry, timeout defaults,
      step caps, and reusable runtime accounting.

## Implementation

- [x] T055-03 Add optional profile/ledger support to `AgentLoopRuntime`.
- [x] T055-04 Apply profile timeout and step caps without changing default behavior.
- [x] T055-05 Export safe profile telemetry while preserving existing fields.

## Verification

- [x] T055-06 Run focused/full pytest, Ruff, compileall, build, Specify prerequisites, and diff checks.
