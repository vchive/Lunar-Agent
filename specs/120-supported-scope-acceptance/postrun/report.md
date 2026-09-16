# Feature 120 postrun report

Campaign `acceptance120-glm-5.2-supported-scope-20260917` ran the two registered GLM-5.2
slots once on product `c5695088c83bf69188bd7ae222056c8b63233656`. Registration commit was
`f3b575c5bf86019b27529339c88f6f936a779654`; manifest SHA-256 was
`d8dd67c250161aed751ebf85ae10f330b03c8eedfaeb7356011e4e4ff7f7270e`. Both slot receipts
verified the pushed registration and process cleanup.

## Result

| task | result | provider requests | known tokens | quality / gap |
|---|---|---:|---:|---|
| budget_selection | evaluator preparation timed out; no candidate | 2 | 5,236 | null / null |
| worker_assignment | evaluator preparation timed out; no candidate | 2 | 10,925 | null / null |

Primary and registered-envelope completion are **0/2**. Each first contract request returned a
strict accepted contract. The compiled contracts contained the registered hard
`source` `python_file_count` minimum `2` check (and output checks); no unsupported execution
requirement was added. Neither evaluator compiler request returned a response within the fixed
600-second limit. Both ended as `transport_timeout` during `open_response` at about 600.003
seconds. No evaluator bundle, candidate, output delivery, source evidence, holdout audit or
quality score was produced. Each worker exited with code1 after bounded cleanup; the campaign supervisor completed both slots and reported no remaining observed processes.

There were four provider requests: two completed contract responses and two timeouts. Known
usage is 2,881 input + 13,280 output = **16,161 tokens**. Usage for timeout requests and total
provider consumption remain unknown; cost is unknown. The retained response metadata is private,
bounded and redacted; this report publishes no response body or credential.

The changed source scope is therefore untested on a real delivered candidate. This 0/2 is a
separate denominator from frozen 113/115/117 (each 0/2), and does not establish a WebAgent or
normal-mode comparison or satisfy the old helper-import, dependency, or input-read requirements.
No slot was retried, resumed, replaced or reopened.

See [results](results.json), [diagnostics](diagnostics.json), and [evidence](evidence.json) for
hash-bound durable records. The diagnostics file is observational only; `campaign.py summarize`
never reruns a model or candidate.
