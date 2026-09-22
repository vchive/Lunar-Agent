# Tasks

- [x] T001 Define a strict manifest schema with fresh attempt identity, product/task/input/
      evaluator digests, and the registered fixed budget values.
- [x] T002 Add canonical manifest digest construction and read-only parsing with private-field
      rejection and budget-drift rejection.
- [x] T003 Add ordered six-stage receipt observation with identity and digest binding; report
      absent later stages without promoting primary success.
- [x] T004 Reuse the native candidate-generation receipt parser and reject generation-stage
      outcome mismatches.
- [x] T005 Add offline success, prefix, tamper, ordering, budget, and generation-mismatch tests.
- [x] T006 Add a provider-free campaign-directory byte inventory and read-only audit with bounded
      files/bytes, no-follow file reads, and directory-entry race checks.
- [ ] T007 Add independent artifact/lifecycle and holdout semantic auditors before any real
      acceptance launch. This feature does not authorize or perform a provider attempt.
