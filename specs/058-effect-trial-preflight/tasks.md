# Tasks: Effect Trial Preflight

## Specification and tests first

- [x] T058-01 Record the preflight boundary, credential policy, interpreter binding, and report
  schema in the specification and contract.
- [x] T058-02 Add failing tests for valid readiness, frozen input mismatches, missing explicit env,
  profile digest changes, command/interpreter mismatch, and dependency failures.

## Implementation

- [x] T058-03 Add bounded dependency requirement parsing and exact harness-Python capability probe.
- [x] T058-04 Reuse normal/deep effect validators to implement a read-only preflight runner.
- [x] T058-05 Add `effect-preflight` CLI parsing, JSON output, optional atomic report, and public
  exports without starting a trial.
- [x] T058-06 Keep report fields credential-free and enforce built-in harness `--python` binding.

## Documentation and verification

- [x] T058-07 Add README/contract/quickstart examples for `anyio` and
  `claude-agent-sdk==0.1.81` checks.
- [x] T058-08 Run focused/full tests, lint, compileall, build, Specify prerequisites, and diff
  checks; update HANDOFF with the feature status and remaining real-trial prerequisites.
