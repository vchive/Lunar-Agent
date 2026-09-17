# Feature 128: Independent diagnostic after input admission and local failure reporting

## Problem and scope

Feature 125 compiler self-tests used scalar JSON inputs and passed, while the independent auditor
used object inputs and blocked freeze. Feature 126 now shares real-input format admission with all
synthetic probe suites; 127 adds bounded local stage/reason/index diagnostics. Measure one new
preparation on fixed product b9518570a18e25ad784d00ba864a18ee8e30ac80, with a separate denominator
of one. Do not replay generated responses or reopen a historical attempt.

## Fixed conditions and acceptance

- No product changes. Preserve the entire 125 (originally 123) manual contract, problem_id, input
  limit.json bytes {"limit":3} plus newline, structural profile and eight holdout definitions.
  Valid integer output value (excluding boolean/float) satisfies 0<=value<=limit and has exact
  quality=combined_score=value; invalid output has score0/qualitynull and code valid-value.
- Native compile_evaluator_bundle(snapshot) via AgentLoopRuntime.run_isolated, system+user, no
  tools/history/memory, contract compiler, solver, candidate or source constraint. Compiler once;
  independent auditor once only after native compiler admission/self-tests. No repair or retry.
- GLM-5.2 and the same safe provider identity as125. Native stream:false; temperature/max_tokens/
  reasoning_effort/response_format omitted. 600s/request,1320s supervisor wall including all local
  work,max2requests,160000observed-token stop threshold,5s/holdout. Provider defaults uncontrolled;
  observed token threshold is not a server cap. No resume/fallback/replacement.
- Fresh root `.lunar/diagnostic128-glm-5.2-format-admission-20260917`, one attempt-001; start consumes
  its slot. Registration pins product/runtime/measurement/tests, math/input/profile/holdouts, native
  first-request bytes, safe provider identity and historical specs113/115/117/120 through127.
  Commit and push every registered byte before requests; verify again before worker provider access.
- Only after verified freeze run each of eight registered holdouts once (limits1/3, lower/upper
  violations and valid scores) and independently compare validity/quality/score/constraint code.
  Primary freeze/1, agreement/8, joint/1 remain separate; unrun cases are not successes.
- Preserve passive transport/assistant-text capture and accounting. Add optional local_failure
  only from the exact native typed preparation error and validated diagnostic, during failed
  preparation with no freeze. Contains exactly fixed schema/stage/reason and bounded numeric
  indices; no message/source/probe/path/score. Capture failure cannot replace the native outcome.
  Summarization validates shape and role/request consistency before publishing non-null detail;
  null means unavailable, not success or proof of no local failure.
- New immutable evidence retains markers, native request/usage ledger, optional transport/private
  responses, worker outcome, optional bounded local_failure, frozen inventory and per-holdout
  receipts. Public summary/inventory publish once from retained files without model/harness reruns.

## Limits

One uncontrolled model run cannot establish causal success/latency gain from126/127. Eight integer
holdouts do not prove the entire boolean/float/type rule, generic correctness or real multi-file
solver delivery. Local reason identifies a failed check, not provider/business root cause. Holdouts
are not sent in model context but exist locally; native restrictions are not an OS sandbox.
Historical113/115/117/120 remain separately0/2 and123/125 separately0/1, independent of this result.
