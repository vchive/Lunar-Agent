# Plan: WebAgent-Normal Workflow Checkpoints

1. **Protocol design and boundary audit**
   - Define strict schemas for `master.json`, checkpoint projections, and `workflow/state.json`.
   - Reuse the existing effect-trial receipt/public-projection authority; document all fields that are
     controller diagnostics only.
   - Audit transcript loading, model-profile ledger behavior, cancellation, and resume guards before
     changing implementation.

2. **Controller implementation (after design approval)**
   - Add a small staged workflow controller around `AgentLoopRuntime`, not a second model runtime.
   - Persist master/state/checkpoint JSON atomically with monotonic identifiers and source/request/profile
     bindings.
   - Carry one aggregate usage ledger across master/build/resume and enforce reserved stage deadlines.
   - Integrate `SessionTranscript`, event sinks, process observation, and deterministic recovery proposals.

3. **Offline verification**
   - Use fake model/tool/process executors to test every legal transition and failure boundary.
   - Verify interruption and one-resume semantics, token/time accounting, path confinement, redaction,
     idempotent writes, and no private-harness invocation before a valid receipt.
   - Keep exact-harness tests at the existing `EffectTrialRunner` boundary; do not create a staged
     evaluator or score shortcut.

4. **Pre-register the measurement**
   - Freeze source, public input, selected cases, model/profile, provider snapshot, aggregate ceilings,
     arm order, stage reservation, one attempt per arm/case, and resume policy.
   - Run check-only and dry-run guards, commit the manifest before dispatch, and independently audit it.

5. **Execute and report**
   - Run control and staged arms once each, retaining all failures and unknown scores.
   - Invoke the exact harness only for validated receipts, report cases separately, and compare stage,
     receipt, and resource telemetry descriptively with Feature 068 and the historical WebAgent record.
   - Update HANDOFF and audit artifacts; never backfill or relaunch a finished arm.
