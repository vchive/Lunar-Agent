# Feature 125: Independent diagnostic after the snapshot request clarification

## Problem and scope

Feature 123's single compiler response was accepted by static envelope/source parsing but failed
local preparation; a sufficient defect used input descriptor path instead of target. Feature 124
clarified the native request schema and verified it locally. Measure one new preparation on its
frozen product, with a separate denominator of one. Do not replay or repair the old attempt.

## Fixed conditions and acceptance

- Product eefe389d14c2380ceb7db9089636f6a5ebe15e2a. No product edits in this feature.
- Preserve the entire manually authored 123 contract, input bytes, structural profile and eight
  holdout definitions. The problem_id still ends in 123 to preserve contract identity; the campaign
  and attempt storage are new. limit.json contains integer limit=3; valid integer output value must
  satisfy 0<=value<=limit, maximizing exact quality=combined_score=value. Invalid score0/qualitynull.
- Native compile_evaluator_bundle(snapshot) through AgentLoopRuntime.run_isolated, system+user,
  no tools/history/memory, contract compiler, solver, source constraint or candidate. Compiler once;
  auditor once only after native compiler parse/source/self-preflight acceptance. No manual repair.
- GLM-5.2 and the same provider safe identity as 123/120. Native stream:false; temperature,
  max_tokens, reasoning_effort and response_format omitted, provider defaults uncontrolled.
  Same limits:600s/request,1320s supervisor wall including local work,max2 requests,160000 observed
  token stop threshold (not server cap),5s per holdout. No retry/resume/fallback/replacement.
- One fresh root diagnostic125-glm-5.2-snapshot-protocol-20260917, one attempt-001; start consumes
  its slot. Registration pins current product, runtime, measurement code/tests, contract/input/
  profile/holdouts/request bytes, provider metadata and enumerated prior campaign/spec files
  (113/115/117/120/121/122/123/124). Commit
  and push registration before any real request. Old manifests/evidence/slots remain untouched.
- Only after verified freeze, execute eight fixed holdouts once each: limits1/3, lower/upper bound
  violations and distinct valid scores, schema-valid outputs. Independently compare exact validity,
  quality, combined_score and valid-value error code. Primary freeze/1, agreement/8 and joint/1
  remain distinct; uncalled audit/unrun holdouts are absent, not successes.
- Preserve frozen request ledger and passive transport/assistant-text observation, known usage and
  unknown totals/costs, new-session supervision and cleanup. Private response/source stays local;
  public results contain safe counters, hashes, scores and fixed classifications only. Read-only
  summarization does not invoke model, evaluator, candidate or historical verifier.

## Limits

Same task and budget narrow differences but a single uncontrolled model run is not causal evidence
of the prompt's effect or latency gain. Native-compatible evaluators may derive input paths from the
contract; success does not prove literal target lookup or general correctness. No real multi-file
solver delivery or external producer claim. Eight holdouts do not fully exercise the type rule.
Definitions exist locally but are not supplied as model context. Native restrictions are not an OS
sandbox; transport milestones do not establish provider queue/compute/receipt/billing. Historical
113/115/117/120 remain separately0/2 and123 remains0/1, regardless of the new result.
