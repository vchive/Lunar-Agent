# Tasks

- [x] T001 Freeze the CLI option name, integer bounds, omitted-value legacy behavior, handoff
      persistence, continuation matching, standalone decision, and Feature 139 handoff boundary.
- [x] T002 Trace `solve`/`resume`/`answer` parsers, automatic mode validation, evolution request
      payload, override checks, argument overlay, and `_solve_evolution()` generator construction.
- [x] T003 Add early validation for `--candidate-generation-max-steps` and reject unsupported
      modes before Store mutation, runtime construction, preparation, child creation, or provider
      admission.
- [x] T004 Persist an explicit candidate-step value and source marker in the automatic handoff;
      restore it on continuation; reject mismatches and injection into legacy handoffs.
- [x] T005 Construct and pass `CandidateGenerationBudget` through fresh and resumed native
      automatic multi-file generation, binding its timeout to the resolved candidate request
      timeout and preserving Feature 136/140 identity and receipt semantics.
- [x] T006 Add focused offline tests for parser bounds, mode rejection, payload redaction,
      fresh/resumed propagation, omission/legacy behavior, mismatch failure, runtime/profile
      ceiling independence, and no-provider/no-child side effects.
- [x] T006a Correct the lower-profile completion receipt projection only after validating a
      complete effective count tuple; cover profile success/exhaustion and malformed, missing,
      inconsistent, or over-authority metadata without changing receipt validation.
- [x] T007 Add regression coverage proving standalone `evolve-bundle`, explicit profiles,
      single-file, deterministic, command, and producer paths retain existing behavior and do not
      acquire the new budget implicitly.
- [x] T008 Run focused/shared regressions, Feature 140/139 offline suites, Ruff, compileall,
      Specify prerequisites, `git diff --check`, and Feature 131/134 byte/SHA inventories. Record
      exact results without launching a campaign.
- [x] T009 Complete independent review, update `HANDOFF.md` only if the final product state and
      Feature 139 blocker wording are both accurate, then commit and push the verified product
      change. Do not register or launch Feature 139 in this feature.
