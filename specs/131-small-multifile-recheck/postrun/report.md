# Feature 131: contract accepted, evaluator compilation timed out

The sole registered automatic multi-file attempt ended with **primary 0/1, preparation 0/1,
holdouts 0/8 executed and joint 0/1**. The contract compiler completed and the native analyzer
verified the contract, but the evaluator compiler request timed out while opening the response.
No evaluator was frozen and no candidate, delivery or holdout execution followed. Official
quality and gap are null; the task's known optimum remains 3.

Registration commit `1993f112323f018e791c34b4e09176a2789ebdc5` was pushed to `origin/main`
before the campaign started. Product `c730483080d5f53e5bb2d24e4bb2d2d9f45e984e` stayed fixed;
manifest SHA-256 is
`5d4f42808eb00e1e0c5fc9258256d4f72439dd788a9dc2fbe91389da522cf43e`, with 78 product,
16 measurement and 153 historical pins. The sole root is
`.lunar/acceptance131-glm-5.2-small-multifile-20260917`. No retry, resume, replacement, repair,
fallback or extra manual request occurred. Historical campaigns remain sealed.

## Observations

| Item | Retained result |
| --- | --- |
| Provider/model | Registered provider identity, GLM-5.2 |
| Contract compiler | HTTP 200 in 25.237246s; native contract and plan persisted; `contract_verified=true` |
| Contract usage | 3656 tokens: 1754 input + 1902 output |
| Contract request | 8740 bytes; SHA-256 `ad96fc9ffb5fe939aef9f995a054790ebd794d26ca4734f58c6c4d9799d88d82` |
| Evaluator compiler | `transport_timeout` after 600.004296s; no HTTP status or response body |
| Evaluator request | 18920 bytes; SHA-256 `004c13a6df4bb61514ea6bf5bb8c3474d9f55fc4a3c9fcf69b6cd4becae06377` |
| Last local transport milestone | `wait_response_headers` while opening the evaluator response |
| Total usage | Unknown/null because the timed-out request has no usage record |
| Supervision | 626.813936s; worker exit 1; cleanup verified; remaining observed PIDs `[]` |
| Retained evidence | 21 files, 155485 bytes; every retained size/SHA-256 entry reverified |

The first request's HTTP 200 is transport evidence, while native parser and analyzer acceptance
establish contract success. It does not establish evaluator, candidate or delivery success. The
Feature 129 missing-`status` rejection did not recur in this one same-task observation, but one
observation cannot establish that Feature 130 caused the difference or measure general
reliability.

The second request failed in the model transport's `open_response` phase, with the final local
milestone `wait_response_headers`. This was an evaluator **generation request** timeout, not an
evaluator execution timeout. The milestone cannot distinguish provider queueing, model generation
or another remote delay. Its unknown usage means the complete run total must remain null; the
known 3656 tokens from request 1 are not a complete total.

## Read-only analysis and evidence boundaries

Post-run summarization read the retained `.lunar` campaign evidence without modifying it and
published `results.json` plus `evidence.json` once under this postrun directory. It did not inspect
or publish private response text or generated source, and it did not execute captured output.
Credentials remain redacted. The report only uses public counters, hashes, transport metadata and
native status projections.

The results SHA-256 is
`8552b60169378416a29c8960e025ac40ff85262280c25cdd448782e420a26a07`; the evidence inventory
SHA-256 is `68e3728a2d4544b8865dea13ea358e22c261d8fda6ef05cd0907b903aab82abb`.
Independent post-run review found no blocking inconsistency in the result, inventory, cleanup or
interpretation.

Two non-blocking reporting issues remain. The durable SQLite parent run row is still `running`
although the CLI and worker have failed, cleanup succeeded and no observed PID remains. This does
not change conservative scoring, but parent terminal-state convergence should be fixed. Also,
`results.json` does not project the raw HTTP status retained by `transport.jsonl`; its first usage
row has `response_status=null`. A future summary schema should expose the verified transport status
without requiring the private sidecar.

## Interpretation and next work

There is still no successful real automatic multi-file delivery. Feature 128 separately proves
evaluator preparation 1/1 and holdouts 8/8 for its diagnostic; it does not fill this denominator.
Feature 129 remains 0/1, and no historical score changes. No WebAgent parity or broader model
performance claim follows from Feature 131.

Before registering another real attempt, improve evaluator-generation timeout semantics and parent
terminal-state convergence, and project verified HTTP status into the public result. Any later
measurement requires a fresh registration and independent slot; Feature 131 must not be reopened.

Results: [results.json](results.json). Retained inventory: [evidence.json](evidence.json).
Validation: [validation.md](../validation.md).
