# Tasks: Fixed-Budget Independent Measurement

- [x] T062-01 Freeze the identity, scope, model, case, and budget.
- [x] T062-02 Define immutable slot, terminal outcome, and denominator semantics.
- [x] T062-03 Prepare exactly two isolated attempts and audit pre-execution identity.
- [x] T062-04 Execute each slot once and preserve every outcome.
- [x] T062-05 Aggregate and reconcile the durable campaign evidence.
- [x] T062-06 Document the result, limitations, and clean repository state.

Validation is stored in the ignored campaign directory. Both slots terminated in the subject stage
with the bound diagnostic `runtime/budget_exceeded`; neither produced a subject receipt or harness
score. The frozen denominator is 2, with 0 valid attempts and null score summaries. The slots ran
concurrently through one provider configuration, which is retained as a limitation.
