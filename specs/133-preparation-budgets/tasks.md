# Tasks

- [x] T001 Specify request and total-wall policy, defaults, bounds, timing boundary and legacy compatibility without changing frozen profile bytes.
- [x] T002 Persist/restore the request value across solve, resume and answer, and route it to compiler/auditor requests while retaining execution timeout.
- [x] T003 Add wall CLI validation, persistence/restore and mismatch rejection, including defaults, origins and legacy-unbounded policy.
- [x] T004 Enforce a monotonic deadline from durable attempt start through local preparation and publication; clip requests and preflight to remaining time.
- [x] T005 Record bounded exhaustion diagnostics, preserve Feature 132 request evidence and Feature 116 explicit recovery/idempotency.
- [x] T006 Project all three budgets separately in JSON/text with verified explicit/default/persisted/legacy origins.
- [x] T007 Complete deterministic offline tests for clipping, expiry, prepared-event/child prevention, retained-material recovery, retry under persisted policy and compatibility.
- [x] T008 Run final focused/full regression, lint, compileall and diff checks; record exact results and limitations.
- [x] T009 Complete independent review, update handoff, commit and push the verified full implementation.
