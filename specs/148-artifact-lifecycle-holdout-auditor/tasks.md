# Tasks: artifact/lifecycle and holdout receipt auditor

- [x] T001 Define canonical audit-request, holdout-declaration, holdout-receipt, boundary-result,
      and combined-report schemas with bounded fields and private-field rejection.
- [x] T002 Add fresh-identity and manifest-binding checks that cannot consume Feature 131/134/139
      identities as a new attempt and cannot be used as a launch preregistration.
- [x] T003 Implement the read-only artifact/lifecycle adapter over
      `validate_automatic_solve_bundle`, `inspect_candidate_execution_record`,
      `inspect_candidate_evaluation`, and `inspect_bundle_parent_delivery`, retaining Feature
      147's native generation validation and requiring actual successful/valid native outcomes.
- [x] T003a Check orchestration task ownership/discriminator, reciprocal child links, execution
      identity/policy, one-slot identity uniqueness, and durable-delivery-before-parent-success
      ordering in a consistent read-only Store view. Reject late success after a terminal write.
- [x] T004 Preserve native inode/device and snapshot semantics; report relocation, uncertainty,
      changed bytes, and missing receipts without repairing or reinterpreting them.
- [x] T005 Implement canonical holdout declaration and receipt parsing with exact ordering,
      identity/digest binding, retained-output comparison, native/process exit and cleanup
      requirements, and exactly eight holdouts bounded at 5,000 ms each.
- [x] T006 Produce primary/joint eligibility projections, explicit no-side-effect flags, and
      first-problem reporting while leaving official acceptance counters unchanged.
- [x] T007 Add provider-free positive and negative fixtures for each lifecycle boundary, holdout
      gaps/tampering, copied-directory inode mismatch, and audit reentrancy/read-only behavior.
- [x] T008 Add an audit-only API/CLI surface only if it does not alter launch or continuation
      behavior; reject attempts to pass audit output as a launch manifest.
- [x] T009 Run focused, shared, static, compile, SDD, and diff checks; document actual counts and
      known limitations. Audit fixtures must not execute retained source, evaluators or holdouts;
      shared regressions remain offline, with no providers or real campaigns.
