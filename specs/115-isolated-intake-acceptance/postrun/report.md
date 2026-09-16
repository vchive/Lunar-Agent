# Post-isolation GLM-5.2 acceptance: 0/2 completed

Both preregistered attempts finished without a delivered solution. Budget selection passed
contract intake, then its evaluator compiler request timed out. Worker assignment timed out
at contract intake. No frozen evaluator, candidate or delivery was produced; quality and evaluator
agreement remain unavailable. Primary and registered-envelope completion are both **0/2**.

Registration `acfb815` was pushed before launch. Product bytes are fixed at
`5e2568f286b709c7f8bd4c883bf654582908e736`, and the unchanged manifest digest is
`a4be47bfc2d6d02446fac1834f34ce8176a92017694cb6d71f8508e364f8a6c9`.
All 15 fixed-condition fields match the separately frozen Feature 113 campaign.

| Task | Furthest observed stage | Failure | Wall seconds | Known usage |
| --- | --- | --- | ---: | --- |
| Budget selection | Contract compiled; evaluator compilation requested | 180 s HTTP timeout opening response | 300.944 | 8,625 tokens plus unknown timeout consumption |
| Worker assignment | Contract compilation requested | 180 s HTTP timeout opening response | 180.943 | Unknown; no usage-bearing response |

Exactly three requests were made: one accepted `glm-5.2` response and two transport timeouts.
The accepted response reported 1,109 input and 7,516 output tokens. **8,625 is a known subtotal,
not total consumption**; both timed-out requests have unavailable usage and monetary cost is
unknown. The zero known-token counter in the second slot means no reported sample, not zero spend.
Both guards stopped further requests after the error. No retries, answers, replacements or model
fallbacks occurred. Both supervisors cleaned all observed descendants; total task wall time was
481.887 seconds, with no 1200-second attempt timeout.

One private parsed-response sidecar was captured: a complete, valid 5,768-byte contract response
without truncation or redaction, no tool calls. There is no response text for either transport
timeout. Its bytes are not published as a model prompt or used to repair/retry the task.

## What changed relative to 113

113 completed 0/2 and accepted zero contracts; 115 completed 0/2 and accepted one contract.
The successful contract confirms the repaired intake can produce an accepted result in one of
these attempts. It does not establish a general success-rate improvement or isolate the effect
of dispatch from the changed schema prompt, provider latency or sampling. The two /2 denominators
remain separate. The 24 synthetic evaluator holdouts could not run because no evaluator froze.

## Confirmed state and diagnostic issue

After the first slot's evaluator preparation error, the CLI exited 2, with an empty JSON stdout
and stderr `evaluator compiler failed: runtime_error`. The parent retained its accepted contract
but remained `awaiting_input`; no corresponding user question or preparation-failure event was
recorded. Its remaining `waiting` tasks were ordinary DAG dependencies with null input questions.
The second slot has an ordinary durable `task_failed`/`run_failed` record and CLI failure result.

Read-only inspection confirms `Store.settle_run`, `pending_input` and `answer_input` treat dependency
waiting as user waiting. This can expose a nonexistent question and route an answer incorrectly.
The next repair should distinguish genuine input requests from dependency waits and persist an
explicit, recoverable preparation failure. An explicit future resume should reuse the contract;
this frozen campaign was not resumed. Raising timeout budgets alone would not fix the misleading
state or missing diagnostics, and no in-place budget change was attempted.

## Evidence and limits

- [Structured results](results.json), [diagnostics](diagnostics.json), [private artifact inventory](evidence.json).
- Local data: `.lunar/acceptance115-glm-5.2-isolated-intake-20260916/`.
- Two hand-authored tasks, one attempt each; no concurrent control or WebAgent run. Provider
  server defaults and response latency remain uncontrolled. These failures do not measure
  generated-evaluator correctness, multi-file algorithm quality or evolution benefit.
