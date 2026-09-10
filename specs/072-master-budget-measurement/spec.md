# Feature 072: Master Budget Measurement

## Problem and P1 story

The user questions whether the 300-second Master deadline is sufficient. Feature069's two staged
attempts timed out before returning a validated plan; its two normal subjects produced valid
solutions in 3068.032 and 3331.589 seconds. Those failures do not establish an adequate planning
budget. Tools were subsequently corrected in Features070/071, so historical attempts cannot
serve as the new control. As an evaluator, I need fresh controlled attempts that distinguish
Master handoff from final independently verified solution validity.

## Registered design and acceptance criteria

1. Use product source 5c89e049c184c52090f665131e3290ea3359bc04, GLM-5.2 and the existing authorized
   CC Switch endpoints, public inputs, profile and exact harness. Do not run WebAgent or query the
   company platform. Each case has one fresh attempt under each Master budget, with no replacement.
2. Fixed order: wave1 slot1 sheet_metal_nesting/master_300 and slot2
   china_post_pickup_optimization/master_1200; wave2 slot3 sheet_metal_nesting/master_1200 and
   slot4 china_post_pickup_optimization/master_300. Concurrency is two, with a complete wave barrier.
   All slots use arm=S; budget_arm is the separate experimental grouping.
3. Only policy difference is master_seconds=300 versus 1200. Both retain build_seconds=2400,
   reserve_seconds=120, checkpoint_after_rounds=32 and at most one same-process continuation.
   Aggregate ceilings stay 5400 seconds, 200 tool calls and 8000000 cumulative tokens; unknown
   costs remain null. No prompt, tool, role, continuation or evaluator redesign is included.
4. Freeze source, scripts, tests, profile, all four workflow identities, public/private input
   identities, historical anchors and endpoint hashes. Independently audit and dry-run offline;
   commit registration/audit/dry-run before exclusive one-shot launch. Frozen bytes remain unchanged
   throughout execution and final audit. Keys are loaded only into process environments.
5. EffectTrialRunner remains the sole subject receipt/public-input gate and exact-harness authority.
   A plan, checkpoint, candidate or worker exit code alone never establishes validity. Report each
   case separately; per budget group planned denominator is two. Unknown scores/complete usage/cost
   remain null, historical samples are excluded and cross-case quality means are prohibited.
6. Record validated plan handoff and observed Build evidence separately from final validity. Read
   durable evidence without invoking recovery constructors. Precise Master duration is null: current
   state does not preserve an authoritative per-stage clock. Do not infer duration from mtimes or
   final aggregate usage. A long-budget handoff alone does not establish it needed more than 300s.
7. Offline tests cover per-group bindings/tamper rejection, staged CLI paths, shared ceilings,
   Master timeout/invalid-plan/plan-to-Build behavior, exclusive launch, wave barrier/no replacement,
   null-aware summaries and refusal to finalize incomplete or inconsistent evidence.

## Interpretation and limitations

1200 seconds is a candidate upper bound, not a proven sufficient budget. If fully used, the
theoretical remaining window after reserve is 4080 seconds (68 minutes), before overhead.
Master consumes shared tokens/tools; Build starts with the original task and accepted plan, not
the raw Master history. Build's 2400-second boundary is cooperative after durable tool rounds,
not a hard 40-minute stop. Remaining-time hints and downstream available budgets necessarily
change with the treatment. Single attempts are descriptive; provider contention/cache are
uncontrolled. This is not a WebAgent reproduction or a universal framework comparison.
