# Validation: artifact/lifecycle and holdout receipt auditor

**Status**: Specification skeleton; implementation and validation are pending
**Validation mode**: provider-free, read-only, no campaign launch

No Feature 148 implementation exists yet, so this document intentionally records the required
validation shape without claiming passed tests or real acceptance results.

## Required focused checks

- Canonical audit-request and holdout declaration/receipt parsing, duplicate-key rejection, size
  limits, private-field rejection, identity binding, ordering, and digest tamper cases.
- Preparation-only and intake-only parent projections remain incomplete/unverifiable.
- Native parser-complete generation is required; a later valid-looking execution cannot fill a
  missing generation receipt. A recorded failed execution or invalid evaluation remains failed.
- Execution records are accepted only through `inspect_candidate_execution_record`; uncertain,
  changed, mismatched, and copied/inode-relocated records cannot become successful execution.
- Evaluation is accepted only through `inspect_candidate_evaluation`; altered evaluator, input,
  output, report, or evaluation digest fails closed.
- Selection and delivery are accepted only through their existing identity-bound receipts and
  `inspect_bundle_parent_delivery`; child completion cannot settle the parent in the audit.
- Parent/child/orchestration ownership and policy bindings are checked independently; premature
  parent success, missing event order, extra execution identities, and late success after budget
  failure or cancellation cannot become a verified lifecycle.
- Holdout missing, duplicate, extra, out-of-order, unknown, failed-exit, failed-cleanup, and
  digest-mismatch cases remain non-joint; all declared holdouts plus a valid primary chain are
  required for `joint_eligible`.
- Repeated audit is byte/read-only idempotent and emits no Store events, task transitions,
  subprocesses, provider calls, or artifact mutations.

## Required shared checks

Run the existing Feature 147 observer and inventory suites, candidate execution/evaluation and
bundle-delivery regressions, automatic solve lifecycle regressions, Ruff, compileall, SDD checks,
and `git diff --check`. Record exact command output and counts after implementation; do not infer
counts from earlier runs.

## Evidence and limits

The validation report must state `provider_called_during_audit=false`, `executed_during_audit=false`, and
`real_acceptance_claimed=false`. It must preserve the historical Feature 131/134/139 evidence and
their frozen counters. A passing provider-free audit fixture demonstrates semantic checker
behavior only; it does not establish a real-model end-to-end result, WebAgent comparison, or a new
acceptance denominator.
