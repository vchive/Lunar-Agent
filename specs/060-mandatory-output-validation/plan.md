# Plan: Mandatory Output Validation

1. Reproduce the `any` bypass with the existing one-task structured-output plan and fixture
   runtime; assert failure before promotion/delivery and retain a valid control case.
2. Add a bounded `evaluate_output_contract` helper in `evaluator.py`. Check declared outputs
   independently using existing single-file acceptance rules, then aggregate their results.
   Inspect optional path components without equating unsafe paths with absent outputs.
3. Remove the controller's syntactic output-rule deduplication. Route normal/delegated evaluation
   and final materialization through the shared helper; use it in ContractCandidateRunner too.
4. Cover optional paths, 32 declarations, retry repair, candidate execution and materialization
   with deterministic local fixtures. Keep existing base/acceptance, no-output and delivery tests.
5. Update README/HANDOFF and complete all standard repository quality gates before commit.

The helper consumes validated OutputSpecs and retains structured leaf diagnostics. It does not
merge the user acceptance expression with generated rules or weaken the acceptance parser's limits.
