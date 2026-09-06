# Tasks: CLI Runtime Model Profile Provenance

## Specification and tests first

- [x] T056-01 Review ordinary CLI runtime construction and detached resume paths.
- [x] T056-02 Add failing tests for profile parsing, validation, propagation, and fingerprinting.

## Implementation

- [x] T056-03 Add bounded `--model-profile` loading through `ModelProfile.from_dict`.
- [x] T056-04 Pass profiles into ordinary `HermesSessionRuntime` instances.
- [x] T056-05 Preserve profile identity across detached/resume and compiler fingerprints.

## Verification

- [x] T056-06 Run focused/full pytest, Ruff, compileall, build, Specify prerequisites, and diff checks.
