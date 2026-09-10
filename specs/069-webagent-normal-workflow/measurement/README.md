# Feature 069 registered measurement

Campaign: `real-eval-glm-5.2-staged-20260910`.
Product implementation: `80f5af10f4a25dab5c5aa2ad767e3b78994f34a3`.
Manifest SHA256: `07781f3390586e49c2c521012e7981350c06215e6c7103a865a97f25597e423e`.

The question is whether the opt-in master/build/cooperative continuation workflow can deliver
evaluator-valid solutions on two cases with strong existing platform results, under the same
aggregate ceilings as the normal control. This is a descriptive, one-attempt-per-case-arm study.
Planning, prompt, history and output contract change together; an observed difference cannot be
attributed to continuation alone. No WebAgent execution is required or authorized by this protocol.

## Fixed attempts and schedule

| Slot | Wave | Arm | Case |
| --- | --- | --- | --- |
| 1 | 1 | M: ordinary normal control | sheet_metal_nesting |
| 2 | 1 | S: staged | china_post_pickup_optimization |
| 3 | 2 | S: staged | sheet_metal_nesting |
| 4 | 2 | M: ordinary normal control | china_post_pickup_optimization |

Concurrency is two. Both wave-one processes must terminate before wave two starts. Every slot
has one fresh native trial and one attempt. A failed, invalid, missing or interrupted attempt keeps
its slot. There are no retries, replacements, adaptive policy changes or historical attempts in
the denominator. A cooperative continuation stays inside the existing staged subject process;
it is not a new trial or an API-failure retry.

Both arms use `glm-5.2`, 5400 seconds, 200 tool calls and 8,000,000 cumulative tokens.
The model profile digest is
`da362bcb878a675f2c92dab88d022cfa40f6ef95db54871deb8f71e481c4968b`.
Cost ceiling and input/output prices are absent; cost remains null. The unchanged profile's
`thinking_budget=0` is not evidence that the provider disables reasoning.

S has master=300 seconds, build=2400 seconds, finalization reserve=120 seconds and a cooperative
checkpoint after 32 complete durable tool rounds. Reservations are inside the aggregate 5400
seconds, with one shared usage ledger. Build boundaries are cooperative: a single in-flight
operation can consume the remaining window. Unknown usage, API timeout and rejected budget
terminate without continuation. Equal ceilings do not imply equal generation time.

The subject outer process timeout is 5430 seconds. Exact-harness extractor/evaluator phases each
retain the existing 1800-second limit; their outer process has 3630 seconds. A slot worker has a
9300-second outer limit, followed by at most 10 seconds of termination grace. All four dispatches
share one authorized CC Switch configuration snapshot; credentials are passed only in the relevant
child environment. Endpoint hashes are rechecked against Feature 068 without a provider probe.

## Inputs and authority

`manifest.json` freezes 37 product Python source files against the implementation commit,
74 executable/test/input files, and eight prior evidence anchors. Both arms for a case receive
the same canonical native request and public projection. Staged configs additionally bind the
request/profile/source digest and unique run/attempt IDs. Previous candidate workspaces are never
copied. Public-only projection is an input contract, not an operating-system sandbox.

The official 1.10.6 case content, extractor and evaluator hashes match Feature 068. The existing
dedicated harness Python and installed dependency versions are checked locally. The public/private
case kit and runtime dependencies remain local; the manifest records hashes and paths only.

Historical baseline values come from the already audited GLM-5.2 company-platform experiment
`fmexp-ac8297cd-53a6-4c1f-aa06-49751bc6ad05`. Each selected case had three evaluator-valid records.
The proven family is AgentServer/OpenCode; it is not evidence of a particular legacy WebAgent or
v2.5 commit. Normalization maps actual `extracted`/`scored` records to the native `completed`/ready
schema, retaining their scores and converting zero-based run indices to one-based. The resulting
baseline is explicitly descriptive and conclusion-ineligible, and stays outside subject workspaces.

`worker.py` calls the unchanged `EffectTrialRunner`. Only an accepted score-free subject receipt
and unchanged public inputs can open the exact harness. Candidate presence, `build_ready` and
checkpoints never confer validity or authorize scoring. The subject and harness process
environments expose separate required keys. No provider value enters argv or control artifacts.

## Observations and analysis

The primary result is per-case exact-harness validity following an accepted subject receipt.
Each arm always has planned=2. Report starts, terminations, accepted subject receipts, accepted
harness receipts, extraction outcomes, scored and valid counts separately. During execution,
unresolved slots remain explicit; a partial valid/planned fraction is not a final failure count.

Preserve missing scores, complete usage and cost as null. Even an accepted harness receipt with
failed extraction is unscored; its placeholder zero is not a quality observation. Report actual
validity/overall/quality by case, without pooling unlike case scores or claiming statistical
superiority. Prior Feature 068 results and platform records are descriptive context only.

Secondary evidence includes subject/harness wall durations, aggregate accepted usage when present,
interaction turns, workflow stage/checkpoint state and whether the single continuation was used.
Workflow and failure diagnostics are partial, non-authoritative evidence. File-path observations
cannot establish first-valid-candidate time; that measure remains unavailable. Provider caching
and resource contention are uncontrolled. Missing process IDs stay null.

The summary is strictly read-only: it verifies outer/worker startup and termination identities,
worker outcome/report hashes, native state/record digest linkage, the native record schema and
native case-report projection. It never invokes the native record-backup restoration path and
never dispatches a subject or harness. All raw slot evidence is retained.

## Verification and operation

`prelaunch-audit.json` records the independent audit of actual frozen evidence.
`dry-run.json` records 26 passed checks in eight scenario groups: deterministic control/staged
success, one continuation, timeout/unknown-usage candidate retention without scoring, native
worker receipt gates, environment split, exclusive starts, wave ordering, read-only summary,
digest tampering and local process-group timeout cleanup. The subprocess has a scrubbed
environment, temporary fixtures and blocked network/CC Switch access. Model calls=0.
The full suite has 874 passing tests; Ruff, Specify prerequisites and diff checks pass.

Run commands from the repository root:

```sh
.venv/bin/python specs/069-webagent-normal-workflow/measurement/campaign.py --check-only
.venv/bin/python specs/069-webagent-normal-workflow/measurement/campaign.py --dry-run
.venv/bin/python specs/069-webagent-normal-workflow/measurement/campaign.py --launch
.venv/bin/python specs/069-webagent-normal-workflow/measurement/campaign.py --summarize
```

The first two commands require a fresh unstarted campaign. Launch requires committed, unchanged
manifest/audit/dry-run evidence and writes an exclusive start marker before dispatch. Never run
launch again after that marker exists. During execution only `--summarize` is appropriate.
Runtime evidence is under `.lunar/real-eval-glm-5.2-staged-20260910/`; completion creates its
`terminated.json` and `summary.json`. Measurement scripts, tests and product source must remain
frozen until all slots terminate. T069-07 closes only after all four outcomes and final evidence
have been independently audited and reported.
