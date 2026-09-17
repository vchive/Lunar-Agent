# Feature 123: One small real evaluator-preparation diagnostic

## Problem and scope

120 completed contract generation but both evaluator requests timed out before final response
headers.121 fixed prompt protocol gaps;122 added truthful local transport milestones. Test the
frozen122 product on one small synthetic evaluator preparation, without rerunning old task slots.
This is a diagnostic of generation/preflight/freeze, not a multi-file solver or framework benchmark.

## Fixed conditions and acceptance

- Product519fea5ca70ac1ede3df356ee7391112801ab45d; one newly allocated attempt, denominator1.
- One manually typed contract: limit.json contains nonnegative integer limit; output/result.json
  contains value. One output hard rule: value is a JSON integer (not boolean/float) and0<=value<=limit.
  Maximize independently read value; valid combined_score=quality=value; invalid score0/quality=null.
  Registered input is {"limit":3}. No source/execution requirements or candidate generation.
- Native compile_evaluator_bundle(snapshot) using AgentLoopRuntime.run_isolated: system+user,
  no tools/history/memory, compiler once and auditor only after native compiler parse/source/self
  preflight acceptance. Do not manually call or repair auditor after failure. No contract compiler.
- GLM-5.2 through the same selected provider configuration as120, checked using safe metadata.
  stream:false; temperature/max_tokens/reasoning_effort/response_format omitted, provider defaults
  uncontrolled.600s/request,1320s total supervisor wall (also bounds local preflight), max2 requests,
  160000 observed-token stop threshold, not a server cap. No retry/resume/fallback/replacement.
- Eight holdouts fixed before launch, using limits1/3 and lower/upper violations plus distinct valid
  scores. All satisfy output format/schema. Execute only the frozen evaluator via native snapshot
  helper, once each,5s per holdout within the same task wall. Require validity, exact recomputed
  quality/combined_score and valid-value error code on invalid snapshots. Preserve all outcomes.
- Primary preparation success requires verified evaluator freeze; separately report agreement/8 and
  joint diagnostic success/1. Uncalled auditor and unrun holdouts are absent, not successful.
- Registration pins product, measurement/test/docs, contract/input/profile/holdouts and historical
  evidence plus runtime/provider identity. Commit and push before any provider request. Existing
  root/worker markers prevent relaunch; any started attempt consumes the slot.
- Journal requests before call; retain known usage subtotal and unknown total/cost if incomplete.
  Observe unchanged transport exchange result/failure locally for safe milestone/timing metadata.
  Keep bounded redacted assistant text privately, never publish prompt/response/endpoint/credentials.
  Diagnostic failures cannot alter the native request/accounting. Final public reports project only
  fixed names, counters, safe numbers and hashes; raw generated files stay local.

## Limits

One simple evaluator may work while original business tasks fail; no causal latency comparison,
general correctness, algorithm quality, source behavior or complete delivery claim. Local transport
milestones do not prove server receipt/execution/billing. Generated evaluator code runs as trusted
owner with native AST/files/process restrictions, not an OS sandbox. Holdout definitions are not
supplied as model context but exist in the local repository.113/115/117/120 remain separately0/2.
