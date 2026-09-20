# Feature 139: preparation accepted, candidate protocol rejected

The sole registered `attempt-001` completed with **preparation 1/1**, but **primary and joint
success are 0/1**. No parser-accepted candidate was produced, so candidate execution,
independent scoring, selection, parent delivery, and holdouts were not reached. Official quality
and gap remain null. This is an honest failed end-to-end closure acceptance.

Registration commit `60efeadb1bfd7e7c994ef90a083cd4e6a7fdf2bc` was pushed to
`origin/main` before launch. Product `87d86d9bc78171e7ce772dd9069e133249b81312` stayed fixed.
Manifest SHA-256: `12c62065a98474f857931d6c44b5d6f3abd2547467e5272d7899a4791a59f0d7`.
The unique campaign is `.lunar/real-automatic-multifile-closure-20260920-50min`, with one
`attempt-001`. No retry, resume, replacement, response repair, fallback request, or appended
provider call occurred.

## Registered conditions and observations

| Item | Retained result |
| --- | --- |
| Provider/model | Registered OpenAI-compatible provider identity; GLM-5.2 |
| Task | Maximize an integer value in `[0,3]`; one JSON input, one JSON output, at least two Python source paths |
| Candidate / preparation request / preparation wall / campaign limits | 600 / 900 / 1860 / 3000 seconds |
| Request / observed-token ceilings | 20 requests / 160000 observed tokens |
| Candidate tool budget | 12 tool steps per generation invocation |
| Contract compiler | HTTP 200; contract verified |
| Evaluator preparation | Compiler and auditor HTTP 200; evaluator/profile frozen and verified |
| Candidate generation | 14 requests across two generation invocations; both failed before parser acceptance |
| Holdouts | 0 of 8 executed because the primary gate failed |
| Usage | 17 of 17 requests finished; 72315 input + 63029 output = 135344 tokens |
| Fees | Unknown; recorded tokens do not establish a provider bill |
| Supervision | 811.740448 seconds; native/process exit 1; cleanup verified |
| Evidence | 70 retained files / 298462 bytes |

All 17 transports returned HTTP 200 and every request-ledger outcome is `succeeded`. That proves
the exchanges completed; it does not mean either candidate generation succeeded. The ledger is
complete and verified, has no pending request, and records no request, token, or whole-attempt wall
stop. This run ended with ample registered wall time remaining.

## Candidate failures and state interpretation

The two durable `agent_candidate_generation` receipts are failures with reasons `worker_failed`
and `malformed_candidate`. The first invocation completed seven tool results before the worker
failed; the retained public diagnostics do not preserve a more precise typed cause. The second
used all 12 tool steps and returned candidate source, but its final response contained explanatory
text and a Markdown JSON fence. It also used invalid object values where the protocol requires
arrays. The strict parser correctly rejected the whole response; scratch files are not completed
candidates and were not executed or scored.

The evolution child ended as `offspring_batch_failed` with zero completed, evaluated, or valid
candidates. The worker then recorded a failed `holdout_gate`, so no holdout was run. The persisted
parent status is `succeeded` because intake completed; the effective product status is `failed`
because the linked evolution child failed and no delivery exists. Native and process exit codes
are both 1. Cleanup passed and no observed process remained.

## Interpretation and next work

This run proves that the current real path can compile a contract, prepare and freeze an evaluator,
track 17 real requests, preserve a failure denominator, and stop without promoting partial model
work. It does not establish automatic multi-file delivery, model stability, evolution benefit,
WebAgent parity, or OpenEvolve/Shinka effectiveness.

The next product SDD should keep strict parsing authoritative while making the final candidate
protocol easier for the model to satisfy and retaining a typed cause when the Agent worker fails.
It must be validated offline first. Any later real measurement needs a new registration and slot;
Feature 139 is closed and must not be resumed or repaired. Product-level whole-solve timeout,
cancellation propagation, process cleanup, and detached automatic solving remain Feature 142 work.

Postrun inspection read retained evidence without calling the provider or executing candidates or
evaluators. Feature 131/134 and WebAgent history were not rewritten.

Results SHA-256: `f7c17b673d9eb0844ac84bb1f7fb81b4585aa38e65006baa3a756ac80464b35a`.
Evidence inventory SHA-256: `b4eb46d066a8f14f6f02db3033ebca80aef300f122d4001daabcba7765112629`.

Results: [results.json](results.json). Inventory: [evidence.json](evidence.json).
Independent audit: [audit.md](audit.md). Validation: [validation.md](../validation.md).
