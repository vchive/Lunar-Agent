# Small evaluator preparation diagnostic — 2026-09-17

The independently registered diagnostic finished **0/1 verified evaluator preparations** and
**0/1 joint successes**. The compiler HTTP request succeeded after242.848 seconds, but native
local preparation rejected the generated evaluator before the conditional auditor. No evaluator
was frozen, no candidate was generated, and **0 of8** holdouts ran. Quality/gap remain null.

## Registration and observed result

Registration `034b1847eaf0cc043ac87e179ebd72de5fc1fb90` was committed and pushed before the
single attempt. Product `519fea5ca70ac1ede3df356ee7391112801ab45d` and manifest SHA256
`9d05c7d95eb427f60d7be7a93dbfb8c7c53ec50904169e0391053292315f60a7` stayed unchanged.
The task was the predeclared small integer-limit contract; max2 requests,600s/request and1320s
supervisor wall were unchanged. The unused auditor request was not spent or substituted.

| Observation | Result |
| --- | --- |
| Native compiler model request | One, accepted model/usage, HTTP200 |
| Request body | 12,353 bytes, registered SHA matches actual request |
| Request duration in ledger | 242.848186 seconds |
| Local transport observation | response_headers_received, HTTP exchange1,242766ms from transport start |
| Complete exchange time | 242847ms; the last milestone does not separate earlier connect/write/wait time |
| HTTP body metadata | 79,074 bytes; only length/SHA retained, no raw HTTP body file |
| Parsed assistant text | 5,365 UTF-8 bytes, complete, untruncated, no redaction applied; private only |
| Preparation | EvaluatorBundleError; no frozen bundle |
| Auditor / holdouts | Not called / not executed |
| Known and total usage | 2,688 input +18,143 output = **20,831 tokens**, usage complete |
| Monetary cost | Unknown |
| Supervisor / worker | Exited / exit1,244.044251 seconds including setup and cleanup |
| Cleanup | Verified; no remaining observed process |

Evidence: [results](results.json), [file inventory](evidence.json). The complete retained root has
15 files, all verified by size/SHA. Independent review also verified all77 product,14 measurement
and69 historical pins against registration Git objects and working files. No retry, resume,
replacement, external framework or WebAgent run occurred.113/115/117/120 remain separately0/2.

## Static diagnosis after the run

The retained text exactly matches its original digest
`539bf67cf75939cd61a575e3ac3bec5da6683864a21f5c15020eea825b07268c`. Read-only native parsing
accepts its strict JSON envelope,3,978-byte Python source and three probes. All three probe output
schemas pass; their two valid and one invalid expectations agree with the registered arithmetic
rule. This analysis does not execute the generated source or rerun native preflight/holdouts.

The generated source checks each `request.inputs` entry with `item.get('path') == 'limit.json'`
(source line58). Actual native descriptors have exactly `target`, `source_label`, `size`, `sha256`;
they have no `path`. The subsequent missing-declaration branch therefore returns an invalid report
before reading the staged input, including for valid probes. Its fixed report has validity0,
quality=null and combined_score0. This is a concrete interface defect consistent with the observed
preparation rejection. The original worker retained only the error class, not the exact failing
preflight probe or report, so this is a static explanation rather than an additional run observation.

The output descriptor correctly uses `path`; contract input declarations and profile file entries
also use `path`. They must remain distinct from the runtime input descriptor's `target`.
The snapshot prompt names the request's top-level sections and `inputs/<target>` layout but does
not spell out the input descriptor's exact nested fields.121 documented response/probe/report
shapes; it did not complete this runtime request shape. The next product change should supply
explicit native request/descriptor examples and verify their agreement with actual snapshot requests.
Do not repair and replay this response into the registered attempt.

[Static metadata](static-response.json) and [read-only inspection script](inspect_compiler_response.py)
make the response/pin checks and field mismatch reproducible without publishing its body or code.
The script requires the unchanged123 product/measurement/history pins and private retained capture.

## What this establishes

The smaller request returned within the unchanged600-second limit, then hit a local correctness
failure. This supplies a concrete next repair; it does not establish why120 timed out, a121 causal
latency improvement, remote model execution/queue time, general evaluator correctness or multi-file
delivery. Output-token usage includes whatever the provider reports; no reasoning-content breakdown
was captured. Eight unexecuted holdouts are not eight demonstrated failures or successes.
