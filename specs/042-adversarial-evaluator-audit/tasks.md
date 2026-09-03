# Tasks: Adversarial Evaluator Audit

## Phase 1 — tests first

- [x] T042-01 Test exactly one compiler and one fresh auditor call before solver generation,
  including Agent Loop transcript/tool isolation.
- [x] T042-02 Test auditor context contains contract/profile/evaluator but excludes self probes,
  real values, candidate/search evidence, and machine paths.
- [x] T042-03 Test a weak evaluator passes self probes but fails an independent attack.
- [x] T042-04 Test malformed/unsafe/incomplete audit suites and failed validity/error/order checks.
- [x] T042-05 Test `audit.json` freeze/index/tamper behavior and zero-call resume.

## Phase 2 — implementation

- [x] T042-06 Extract one reusable strict probe-suite parser and canonical serializer.
- [x] T042-07 Add isolated auditor prompt/invocation and shared adversarial preflight.
- [x] T042-08 Bind canonical `audit.json` into manifest, fingerprint, loader, and artifact indexing.
- [x] T042-09 Preserve failure cleanup, compiler privacy, native strategies, and recovery behavior.

## Phase 3 — documentation and verification

- [x] T042-10 Update README and architecture documentation with the two-turn trust boundary.
- [x] T042-11 Run focused/full tests, lint, compileall, diff, quickstart, and Specify checks; mark
  implemented, commit, and push as `vchive` on `main`.
