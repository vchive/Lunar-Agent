# Tasks: Model Profiles and Cost Control

## Specification and tests first

- [x] T054-01 Review HANDOFF P2 requirements and existing runtime usage telemetry.
- [x] T054-02 Add failing tests for profile bounds, credential rejection, usage validation, and
      token/cost budget rejection without state mutation.

## Implementation

- [x] T054-03 Implement `ModelProfile` validation and JSON round-trip.
- [x] T054-04 Implement `UsageLedger` aggregation, integer micro-USD accounting, and hard ceilings.
- [x] T054-05 Export public types without changing runtime/effect score authority.

## Verification

- [x] T054-06 Run focused/full pytest, Ruff, compileall, build, Specify prerequisites, and diff
      checks; record any unrelated baseline failures.
