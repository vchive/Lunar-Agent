# Implementation Plan: Native automatic multi-file CLI candidate budget propagation

**Date**: 2026-09-19
**Spec**: [spec.md](spec.md)

## Scope

This is a small shared-product change required before Feature 139 can register. It adds one
explicit policy field to the conversational automatic multi-file handoff and threads it into the
already implemented Feature 136/140 candidate-generation boundary. A focused review also found
that a lower explicit runtime profile produces incompatible completion receipt arithmetic; this
feature includes a narrow generator projection correction required for its profile compatibility
acceptance criterion. It does not implement a campaign or modify Feature 139 measurement files.

## Technical approach

1. Trace the parser, mode validation, evolution-request payload, override validation, and
   `_evolution_args()` overlay for `solve`, `resume`, and `answer`. Add the candidate-step option
   only to those conversational parsers and reject it outside native automatic multi-file mode.
2. Validate the option using the existing `MAX_CANDIDATE_TOOL_STEPS` authority before runtime
   construction, Store mutation, evaluator preparation, child creation, or provider admission.
   Keep the omitted value absent so legacy handoffs remain semantically unchanged.
3. Persist an explicit value and source marker in `evolution_requested`. Extend continuation
   validation so exact equality is required, omission restores the stored value, and a legacy
   request cannot acquire a new candidate budget. Keep the persisted request bounded and free of
   paths, secrets, prompts, and model text.
4. In `_solve_evolution()`'s automatic `bundle_pipeline` path, create
   `CandidateGenerationBudget("candidate-generation", resolved_steps,
   timeout_seconds=resolved_timeout)` before constructing `AgentCandidateGenerator`. Pass the
   same budget on fresh and resumed child setup; preserve existing pipeline configuration and
   generator fingerprints unless the budget is deliberately part of the recorded authority.
5. Verify the budget reaches `AgentRequest`/`RuntimeAgentAdapter` and that Feature 140's Store
   receipt observes the bound per-request identity. Do not add another counter, timeout, receipt,
   or diagnostic path. The runtime/profile ceiling may only narrow the effective request under the
   existing Feature 136 rule. If a lower profile is active, validate the complete effective
   runtime count tuple and project receipt remaining as candidate authority minus used steps.
   Preserve receipt validation and refuse normalization of inconsistent or oversized metadata.
6. Leave `_prepare_bundle_generator()` and standalone `evolve-bundle` untouched. Add explicit
   regression coverage proving their existing `--agent-runtime-max-steps` behavior and lack of
   accidental candidate-budget propagation.
7. Run focused parser/automatic-bundle/evolution/receipt suites, then Ruff, compileall, Specify
   prerequisites, diff checks, and the full two-stage regression. Independently verify Feature
   131/134 inventories before commit. No provider or provider-generated source is used; local
   repository-owned synthetic candidate/evaluator fixtures remain part of regression validation.

## Expected touch points

- `src/lunar_evolution/cli.py`
- `src/lunar_evolution/agent_evolution.py` (profile-compatible completion count projection only)
- focused CLI/automatic bundle/evolution tests
- candidate receipt integration tests only where needed to observe propagation
- this feature's validation record

No Feature 139 file, historical measurement file, database schema, or standalone bundle product
module should change.

## Policy details

- Product option: `--candidate-generation-max-steps`.
- Valid range: `1..MAX_CANDIDATE_TOOL_STEPS`.
- Omitted option: legacy no-budget behavior, including no Feature 140 generation receipt caused
  solely by this feature.
- Future Feature 139 registration: explicit `--candidate-generation-max-steps 12` with its
  registered `--timeout 600`; the product does not hard-code 12.
- Candidate budget timeout: resolved/persisted evolution request timeout, not preparation wall
  time, campaign wall time, or `--agent-runtime-max-steps`.
- Standalone `evolve-bundle`: unchanged and unsupported by this option.

## Alternatives rejected

- Reusing `--agent-runtime-max-steps` would make a runtime implementation detail serve as a
  candidate authority and would fail for adapters without the Agent loop.
- Hard-coding 12 would silently change default behavior and make future registrations less
  explicit.
- Applying the option to every `evolve`/`evolve-bundle` path would expand the feature into a
  second handoff and receipt contract that Feature 139 does not need.
- Adding the field only to the in-memory generator would let `resume` or `answer` change policy
  and would make the durable receipt unverifiable.
- Adding a second runtime counter or diagnostic would duplicate Feature 136 and risk disagreeing
  with the existing atomic whole-batch boundary.

## Complexity and risk

The main risk is policy drift between fresh and continued conversational runs. Exact persisted
value matching and tests for omission/legacy requests address that risk. The change has no network,
filesystem publication, migration, or irreversible operation beyond the normal future registration
that remains outside this SDD.
