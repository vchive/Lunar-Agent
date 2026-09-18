# Feature 134: evaluator accepted, no final delivery

The sole registered automatic multi-file attempt achieved **preparation 1/1 and holdouts 8/8**,
but **primary and joint success are 0/1**. The native solve and worker exited 1 without a verified
parent delivery. Official quality and gap remain null. This measurement is a failed end-to-end
acceptance, even though all model requests and independent evaluator holdouts completed.

Registration `358f7383e61aec9e702310774b0d5d906978c2f8` was pushed to `origin/main` before
launch. Product `15710bd420d70aa07a06ee9dd4329dfbf1912b2b` stayed fixed. Manifest SHA-256:
`20eb007b2d37b3b4a47d86795b8909213a64dffe36ad57055829c9deb9166ebf`, binding 79 product,
20 measurement and 178 historical files. The unique campaign is
`.lunar/acceptance134-glm-5.2-budgeted-multifile-20260918`, with one `attempt-001`. No campaign
retry, resume, replacement, model-response repair or manual model request occurred.

## Registered conditions and observations

| Item | Retained result |
| --- | --- |
| Provider/model | Same registered provider identity as 131; GLM-5.2 |
| Task | Same input, goal and eight holdouts; maximize integer value in `[0,3]`, at least two Python source paths |
| Candidate / preparation request / preparation wall / campaign limits | 600 / 900 / 1860 / 2400 seconds |
| Request / observed-token ceilings | 20 requests / 160000 observed tokens |
| Contract compiler | HTTP200, 48.362678 seconds, 5131 tokens; native contract verified |
| Evaluator compiler | HTTP200, 346.069923 seconds, 31485 tokens |
| Evaluator auditor | HTTP200, 124.756998 seconds, 13717 tokens |
| Preparation | Verified frozen evaluator and explicit persisted 600/900/1860 policy |
| Candidate stage | Eight model requests across three generation invocations; all stopped at the four-tool budget before returning a candidate |
| Holdouts | Eight snapshots executed once, all eight exactly matched |
| Usage | All 11 requests recorded; 34088 input + 64626 output = 98714 tokens |
| Fees | Unknown; recorded tokens do not establish a provider bill |
| Supervision | 896.395714 seconds; native/process exit1; cleanup verified |
| Evidence | 97 retained files / 327394 bytes |

Observed transport HTTP status is independently bound to each request; ledger success alone is
not used to infer HTTP200. Preparation and candidate time limits remain separate. Both preparation
requests completed below 600 seconds, so this sample cannot establish that the larger preparation
request budget caused success or improved speed.

## Candidate failure and state interpretation

All three generation invocations emitted `agent_step_limit_reached` with `max_steps=4`.
The first two each executed two `read_file` and two `write_file` calls, then requested another
two-tool batch at four consumed steps. The third executed two `read_file` and one `list_dir`
call, then requested two tools with only one step remaining. All 11 executed tools succeeded;
the over-budget batches were rejected in full, as the existing Agent loop requires.

`max_steps` counts individual tool calls, not model turns. The invocations used 3, 3 and 2 model
turns respectively. A returned turn with tool calls cannot also complete the candidate; the loop
requires a subsequent tool-free final text response. No such final candidate was returned here.
The three invocations are generation work within the one registered evolution run, not replacement
campaign attempts. No partial workspace material was promoted or retrospectively evaluated.

The evolution child failed with `offspring_batch_failed`, with zero evaluated and zero valid
candidates. Candidate execution, candidate scoring and parent delivery were not reached. The eight
independent evaluator holdouts did execute separately after the failed solve, as preregistered.
The persisted parent is `succeeded` while the effective CLI status is `failed`: the parent intake
completed, and the CLI projects the failed evolution child's outcome. This difference is not
evidence of an uncorrected preparation recovery defect.

Next SDD work should verify a sufficient explicit per-candidate tool budget and completion
diagnostics with an offline multi-tool fixture, preserving existing whole-batch admission and
final-response requirements. A later real acceptance needs fresh registration and its own slot;
this run must not be resumed or reopened. Raising preparation time is not the next observed need.

## Interpretation and evidence boundaries

The new run reaches candidate generation after automatic contract and evaluator preparation. It
does not establish successful multi-file delivery, stability, evolution benefit or WebAgent parity.
Feature128 and every previous campaign keep their independent denominators. Eight small integer
holdouts do not prove general evaluator correctness or complete boolean/float coverage; the source
constraint counts Python paths and does not prove helper use or input reading.

Postrun inspection reads retained evidence without rerunning models, generated source, evaluator
snapshots or selected candidates. SQLite inspection uses disposable DB/WAL copies. Private prompts,
model text, generated source, endpoints and credentials remain outside the public report.

Results SHA-256: `2a7398a16657d987cfbbe26ffbb5646c3a721f715980b8b7138936637c8d32d0`.
Evidence inventory SHA-256: `f5735d7d8b019c9f6eaa0cb8d5f14dee14ef0d7a63a6ca24a3c66da36b61af5f`.

Results: [results.json](results.json). Inventory: [evidence.json](evidence.json).
Validation: [validation.md](../validation.md).
