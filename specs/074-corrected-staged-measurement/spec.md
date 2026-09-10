# Feature 074: Corrected Staged Workflow Measurement

## Problem and P1 story

Feature072's two1200-second Master attempts returned prose plus JSON fences but failed before
Build. Feature073 fixed deterministic envelope parsing and passed1147 offline tests; it has no
new real validity evidence. The user asks to continue with the real Master-to-Build-to-validity
measurement. As an evaluator, I need two fresh, fixed attempts under the corrected source and
unchanged native receipt and exact-harness authority.

## Protocol and acceptance criteria

1. Freeze source c28e498e539b3ed6e37d743145ba1c38f9b1e9e2 (includes073), GLM-5.2 and the already
   authorized CC Switch endpoints. Use the same two public case projections/private exact harness
   and profile. Do not run WebAgent, query the company platform or probe another provider/model.
2. Exactly two new staged attempts: slot1 sheet_metal_nesting, slot2 china_post_pickup_optimization,
   launched in one wave [[1,2]] at concurrency2. Both retain arm=S and budget_arm=master_1200 for
   provenance. This is one configuration, not a fresh A/B or a replicated stability estimate.
3. Master1200/build2400/reserve120 seconds, checkpoint_after_rounds32, at most one same-process
   cooperative continuation. Shared ceilings5400 seconds/200 tools/8000000 cumulative tokens;
   unknown cost ceiling remains null. Outer subject5430/harness3630/slot9300 seconds unchanged.
   Prompts/roles/tools/harness are not redesigned in this feature. Master consumes the shared
   ledger and wall clock; the Build boundary is cooperative, not a separate hard40-minute stop.
4. New campaign .lunar/real-eval-glm-5.2-corrected-staged-20260910: one attempt per slot, no retry,
   replacement, historical candidate/plan replay or score backfill. Historical069/072 are sealed
   context and never enter the new denominator. Preserve unknown scores/complete usage/cost as
   null and above-one valid scores as observed. No pooled quality mean across the two cases.
5. Freeze all source/scripts/tests/input and helper dependencies. Independently preaudit/dry-run
   offline, commit/push registration and mirrored reports before exclusive launch. No frozen byte
   changes until both attempts end and final audit is sealed. Keys are process-environment only.
6. Observe validated Master records and Build state/transcript separately from final validity.
   Exact Master duration stays null; current runtime has no authoritative independent stage clock.
   EffectTrialRunner remains the sole public-input/subject-receipt gate and exact-harness authority.
   A plan, candidate or checkpoint does not count as a valid solution.
7. Necessary offline checks cover exact two-slot identity/policy/limits and rejection of extras,
   actual private/input/source/dependency changes, exclusive dispatch/no replacement, both staged
   CLI routes, native receipt chain, null-aware fixed denominator and partial/final rejection.
   Reuse pinned existing native fixtures and validators instead of adding a new runtime/evaluator.
8. Finish both slots, independently audit evidence/known process termination, and seal per-case
   results. State the remaining limitations; no causal superiority or stable success-rate claim
   follows from one attempt per case.

## Scope boundary

Only measurement orchestration changes. Runtime remains sourcec28e498; previous campaigns remain
immutable. Work after a newly discovered defect must use an isolated worktree until this batch is
sealed. No crash restart support or broader autonomous retry policy is introduced.
