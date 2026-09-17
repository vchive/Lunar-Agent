# Validation

## Registration checkpoint

Product is fixed at `c730483080d5f53e5bb2d24e4bb2d2d9f45e984e`, the Feature 130 commit that
adds complete contract response envelope examples without changing the strict parser. The same task,
provider, limits, population and seed as Feature 129 are registered under a fresh `/1` denominator.

Feature 128 preparation manifest SHA-256 is
`460da2cedd52c9cf4774139df084129685c1bd686372f2662c5c683421d59a48`.
Feature 129 attempt manifest SHA-256 is
`63a056263387dbee5c9282fffb21182c9eb2fd51b6354cf871b5d4b06af10ad9`.

The six new measurement test files pass **185 tests**. Case, worker and supervision remain
byte-identical to Feature 129; analysis and observation only change private names. Registration
compares every task, runtime, capture, population, sampling, budget and outcome condition to the
fixed 129 manifest. Only campaign identity, product commit and the extra prior-attempt reference
differ. The new root is absent and no real request has started.

Full double-phase regression (`tools/run_tests.py`) passes: current **7353 passed, 1 skipped,
24 deselected in 467.95s**; frozen Feature 123 snapshot **24 passed in 14.00s**. Both JUnit reports
have zero failures/errors and overall exit is zero. Feature 112 quickstart still selects 7 from
scores 1/2/6/7, keeps calls at 1/1/1/4/4 across terminal resume, and delivers one copy.

Ruff, compileall, Specify prerequisites and whitespace checks pass. All 1748 previously tracked
product/spec/test files retain their HEAD bytes. Two independent read-only reviews found no
blocking issue. Neither review nor test made a provider request.

The frozen manifest contains 78 product, 16 measurement and 153 historical pins. Its SHA-256 is
`5d4f42808eb00e1e0c5fc9258256d4f72439dd788a9dc2fbe91389da522cf43e`. Registration commit
`1993f112323f018e791c34b4e09176a2789ebdc5` was pushed to `origin/main` at
2026-09-17T15:40:48Z; the campaign started afterward at 2026-09-17T15:41:12.178551Z with
`HEAD == origin/main`. Registration generation and all pre-run verification made zero model calls.

## Real result

The sole registered attempt ended naturally and was summarized once: **primary 0/1, preparation
0/1, holdouts 0/8 executed and joint 0/1**. Official quality and gap are null. Worker exit is 1,
elapsed time is 626.8139362080256 seconds, cleanup is verified and remaining observed PIDs are
empty. No retry, resume, repair, fallback, replacement or extra manual request occurred.

Request 1 was the contract compiler. It returned HTTP 200 after 25.23724637494888 seconds with
3656 known tokens (1754 input and 1902 output). The request was 8740 bytes with SHA-256
`ad96fc9ffb5fe939aef9f995a054790ebd794d26ca4734f58c6c4d9799d88d82`. Native contract and plan
artifacts were persisted, and the analyzer reports `contract_verified=true`. Thus Feature 129's
missing-`status` contract rejection did not recur in this single same-task sample. This is not
evidence that Feature 130 caused the difference.

Request 2 was evaluator compilation. It ended in `transport_timeout` after
600.004296500003 seconds, with no HTTP status, response body or usage. Its 18920-byte request has
SHA-256 `004c13a6df4bb61514ea6bf5bb8c3474d9f55fc4a3c9fcf69b6cd4becae06377`.
The local failure phase is `open_response` and the final transport milestone is
`wait_response_headers`. This is a model request timeout during evaluator generation, not an
evaluator execution timeout. The milestone cannot identify provider queueing, model generation or
another remote cause. Because request 2 usage is unknown, total usage remains null rather than
being replaced by the 3656 known tokens from request 1.

No evaluator was frozen, and no candidate, parent delivery or holdout execution occurred. The
retained inventory contains 21 files totaling 155485 bytes. Every listed file was rechecked against
its size and SHA-256 with no mismatch. `results.json` SHA-256 is
`8552b60169378416a29c8960e025ac40ff85262280c25cdd448782e420a26a07`; `evidence.json` SHA-256 is
`68e3728a2d4544b8865dea13ea358e22c261d8fda6ef05cd0907b903aab82abb`.

Summarization treated retained `.lunar` evidence as read-only and published the two postrun JSON
files once. Private response text and generated source were neither disclosed nor executed;
credentials remain redacted. An independent post-run audit found no blocking issue in the score,
transport interpretation, cleanup or inventory.

Two non-blocking follow-ups remain. The SQLite parent run row is still `running` even though the
CLI and worker failed, cleanup completed and no observed PID remains; conservative scoring is
unchanged, but terminal-state convergence needs correction. The raw transport sidecar retains the
first request's HTTP 200, while `results.json` does not project that status and its request usage row
has `response_status=null`; the public result projection should expose verified transport status.

Feature 131 does not prove a causal Feature 130 improvement, WebAgent parity, general GLM-5.2
reliability or real automatic multi-file success. Feature 128's separate preparation 1/1 and
holdouts 8/8 remain unchanged. Address evaluator-generation timeout semantics and the two state /
projection follow-ups before registering a fresh independent real attempt; do not reopen this one.

Full report: [postrun/report.md](postrun/report.md). Results:
[postrun/results.json](postrun/results.json). Inventory:
[postrun/evidence.json](postrun/evidence.json).
