# Feature 128: Preparation and all registered holdouts pass

The sole independently registered attempt completed with **freeze 1/1, exact holdout agreement
8/8 and joint success 1/1**. Native compiler self-tests and independent auditor tests passed; the
controller froze the evaluator before running the eight registered holdouts once each. No solver,
candidate generation or multi-file delivery was part of this diagnostic.

## Registration and execution

Registration `38c323cefeccd3ca62539f950029d26b5b769df0` was pushed before launch: the local
origin/main update-by-push record is 2026-09-17 09:28:47 UTC and the campaign started at
09:29:14.049458 UTC. The product stayed byte-identical to
`b9518570a18e25ad784d00ba864a18ee8e30ac80`. Manifest SHA-256:
`460da2cedd52c9cf4774139df084129685c1bd686372f2662c5c683421d59a48`.

The complete 125 (originally 123) contract, input/profile, eight holdouts, provider identity,
GLM-5.2, native sampling omissions and budgets were retained. The problem_id still ends in 123;
the new campaign root and sole attempt belong to 128. Added local_failure capture was declared
separately. No retry, resume, fallback, replacement or manual additional request occurred.

| Stage | Observed outcome | Request duration | Recorded tokens |
| --- | --- | --- | --- |
| Compiler | HTTP 200; source and three self-tests accepted | 380.010s | 30467 (4002 input + 26465 output) |
| Auditor | HTTP 200; five independent probes accepted | 125.088s | 13163 (4561 input + 8602 output) |
| Freeze | Verified native snapshot evaluator, 1/1 | n/a | n/a |
| Holdouts | Eight executed once; validity, quality, score and error code all match | n/a | n/a |

Total recorded usage is complete: **43630 tokens = 8563 input + 35067 output**. Cost is unknown;
campaign quality/gap remain null because these are evaluator checks, not solver delivery scores.
Supervisor duration was 507.148s; worker duration 506.970s. Process exited 0, worker completed at
stage finished, cleanup_verified=true, remaining observed PIDs=[] and local_failure=null.
The local diagnostic was not exercised by this successful real attempt; its failure paths were
validated by the offline tests.

The frozen evaluator fingerprint is
`734a06f600369dac237763579971ed93a00e4a7c6f7cace3e7bdc1856da59bf3`.
Its 2684-byte source has SHA-256
`f83e5fe0bfdacf987b94f8fd6a79c292407eaf56be8b1008ad793cef213bcc2e`.

## Read-only verification

All 63 retained files match the complete inventory by size and SHA-256. All 78 product,
15 measurement and 118 historical pins remain unchanged, as do the 11 pre-registration frozen
implementation/test files and all 1701 prior tracked product/spec/test files. Historical retained
inventories still match: 125 16/16, 123 15/15 and 120 46/46. The measurement summary was published
once; post-run verification did not execute generated evaluators, probes or holdouts again.
Independent read-only audit additionally verified the 74305 retained bytes, the six read-only
frozen files and recomputed fingerprint, and each retained holdout's input/output bytes against
the registration and mathematical oracle (five valid, three invalid). No issue was found.

Both assistant text captures are complete, untruncated and unredacted: 3778 and 1126 bytes, with
SHA-256 `158378ad5a154a566ce886205f9947f6e5c54097161392fb01bd84c5bbd7bdba` and
`21c43c1865ab4591dff5dd079fe9f2d604bde5133c9ab6e36ee477aeaf23dc4c` respectively.
Only safe metadata is published; captured responses and generated source remain private.
Pure native parsing confirms three compiler and five auditor probes, all with JSON object input
roots. No response was repaired or replayed.

Offline reconstruction using the fixed native prompt builders matches both ledger/transport hashes:

- Compiler: 18082 bytes, `c962c62777a4dca45dedfc20ca21af7032af8c46b992162ee43cc6f0afb38c44`.
- Auditor: 20616 bytes, `8a1601d8a1b01aa9cc651bcb2d6a74bdaec1a3a54f6066e2e1ecbd0d922fe91d`.

Both transport records show HTTP 200, one exchange, last_milestone=response_headers_received at
379646/124975ms; whole exchange observations are 380009/125087ms. HTTP bodies have retained
length/hash only (110928/36562 bytes), not raw content. These observations do not separate provider
compute, queue, connection or response waiting time.

Results SHA-256: `4dd1210652b21d573a0cc3dd5d6be18bd81bc48f237cfc71683eebdc78d487ea`.
Inventory SHA-256: `98133455dc0b8c4dec0d8c730edafcb5a602eaafe10f13dc5e095e81d001c6bf`.

## Meaning and next step

This establishes one successful real small evaluator preparation and agreement on the eight
predeclared integer cases. It does not establish general evaluator correctness, full boolean/float
type coverage, causal improvement from 126/127, lower latency, or real multi-file solver delivery.
Historical 113/115/117/120 remain separately 0/2 and 123/125 separately 0/1. Their slots stay closed.

Next independently register a small supported-scope multi-file task through the actual automatic
solve path: contract, compiler/auditor, candidate generation, execution, independent scoring,
selection and parent delivery. Include a deterministic two-source-file requirement and independent
output checks, declare the budget before launch, and preserve the entire failure denominator.
External producer multi-file integration, total-budget/cancellation orchestration and detached
execution remain later work.

Machine-readable artifacts: [results](results.json), [evidence inventory](evidence.json).
