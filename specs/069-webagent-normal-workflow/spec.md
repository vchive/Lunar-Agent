# Feature 069: WebAgent-Normal Workflow Checkpoints

**Created**: 2026-09-09  
**Branch**: main  
**Status**: In progress (control-plane slice implemented)

## Objective

Feature 068 established a useful but asymmetric result: the current Lunar normal session solved
`sheet_metal_nesting` in one attempt, while `china_post_pickup_optimization` consumed its bounded
run without an accepted receipt. The historical WebAgent record used a longer, multi-session
workflow and completed the same class of work. This feature designs the smallest repository-owned
workflow change that can test whether a durable **master → build → checkpoint/resume** boundary
improves completion without importing WebAgent, exposing the private evaluator, or changing effect
receipt authority.

The first measurement is a controlled workflow comparison. It must distinguish a workflow failure
from a case that remains intrinsically difficult under the same model, public input, tools, source,
and total budget.

## Non-goals and authority

- Do not run WebAgent or copy its source, prompts, traces, candidate files, private solutions,
  scores, or evaluator outputs into Lunar.
- Do not send historical WebAgent scores or the private harness identity to the subject. The subject
  receives only the declared public projection and request, as in Feature 068.
- Do not let a master plan, checkpoint marker, local test, or model claim establish validity or a
  score. The effect receipt, unchanged public projection, exact extractor and exact evaluator remain
  authoritative.
- Do not change the benchmark, case selection, effect-kit schema, score domains, or the meaning of
  `validity=0`, partial usage, unknown score, or unresolved termination.
- Do not add unbounded retries, best-of-N attempts, hidden continuation, or a timeout extension after
  observing an outcome.
- Do not change the default normal workflow until the staged variant has a pre-registered result.

## Proposed workflow

The staged variant uses one logical attempt and one aggregate resource envelope, split into explicit
control-plane stages:

1. **Master** receives the same public request and tools. It writes a bounded `workflow/master.json`
   containing the request digest, workspace identity, a short ordered build plan, expected deliverable
   paths, and a plan digest. It may inspect public files and formulate the approach; it may not run
   the private harness or write a subject receipt.
2. **Build** starts only after the master checkpoint passes local schema and workspace-boundary
   validation. It receives the master plan and the same public request. It implements the candidate,
   runs permitted public/local checks, and must atomically preserve a complete candidate before
   expensive refinement.
3. **Checkpoint** is written at bounded intervals and at every clean stage boundary. It records only
   typed control data: stage, workspace tree digest for declared paths, transcript digest, usage
   snapshot, tool-step count, and a monotonic checkpoint number. It contains no private results and is
   never treated as a receipt.
4. **Resume** may reopen the same logical attempt after a process interruption or stage timeout. It
   uses the checkpoint and the bounded session transcript to continue the build. Resume is allowed
   only for a pre-registered interruption policy and within the original total wall-time, tool-step,
   token, and cost ceilings. A resumed process does not reset any ledger or create a new attempt.
5. **Delivery** ends the subject side when the candidate and the repository-owned subject receipt are
   complete, or when the fixed aggregate budget is exhausted. Only then does the controller invoke the
   exact private extractor/evaluator under the existing `EffectTrialRunner` boundary.

The minimum product experiment is **one master stage followed by one build stage, with at most one
resume from a durable checkpoint**. The controller may use a clean process for build/resume, but it
must retain the same run id, workspace, ledger, request digest, model/profile identity, and
attempt-start marker. A stage that times out without a checkpoint is a subject failure; it is not
silently converted into a new attempt.

### Resource accounting

The staged arm and its monolithic control arm use identical aggregate ceilings. The master and build
stages receive reservations for scheduling only; unused reservation returns to the same aggregate
ledger. A stage cannot borrow beyond the aggregate cap, and a resume cannot reset accepted or
observed usage. Suggested first experiment reservations are 15% master / 85% build with a 5% safety
reserve taken from the aggregate rather than added to it; exact numbers must be frozen in the
pre-execution manifest after offline boundary tests.

Stage prompts are protocol text, not an evaluator. They must say to save a complete candidate early,
keep output paths stable, and leave time for atomic writes. They must not contain baseline scores or
private harness details.

## Durable records and invariants

Each staged attempt has a controller-owned record under its attempt workspace:

- `workflow/master.json` — bounded plan projection, request and source identity, no score.
- `workflow/checkpoints/<n>.json` — typed checkpoint projections; write with temporary file then
  replace; monotonic `n` and no overwrite of an existing checkpoint.
- `workflow/state.json` — stage state machine and aggregate ledger state, updated atomically.
- existing `session-transcript.jsonl` — redacted, bounded transcript used only for same-attempt
  resume; transcript contents are not sent to the evaluator.
- existing subject receipt and diagnostic files — unchanged authority and failure semantics.

The state machine is `created → master_running → master_ready → build_running → checkpointed →
resuming → build_ready → harness_pending → terminal`, with typed terminal failures for stage timeout,
resume rejection, budget exhaustion, receipt invalidity, and runtime failure. Transitions must be
monotonic and idempotent. `harness_pending` is entered only after the same receipt/public-projection
validation already required by `EffectTrialRunner`; the harness must never read `workflow/master.json`
as evidence.

A checkpoint is accepted only when all of the following hold:

- run/attempt id, source SHA, suite/case identity, request digest, model/profile digest, and total
  ceilings match the immutable manifest;
- checkpoint number and stage transition are valid and prior state is present;
- every declared path is confined to the subject workspace, regular, and free of symlink escapes;
- usage is a complete typed snapshot or explicitly marked unavailable; unavailable usage never becomes
  zero and cannot extend a ceiling;
- the checkpoint digest is recorded before a process is considered resumable.

## Minimum measurable variants

The first preregistered comparison has exactly two arms, one fresh attempt per arm and per selected
case, using the same model/profile snapshot and aggregate ceilings:

| Arm | Session shape | Purpose |
| --- | --- | --- |
| M (control) | Current single `AgentLoopRuntime.run` session | Replicate Feature 068's current behavior under the new frozen manifest |
| S (staged) | Master → build, one checkpoint, at most one resume | Test whether explicit planning and durable continuation improve receipt completion |

The primary outcome is per-case subject receipt validity followed by exact-harness validity; a score is
reported only for a validated receipt. Secondary outcomes are stage completion, checkpoint/resume
success, terminal reason, accepted/observed usage, tool steps, turns, and time to first complete
candidate. No pooled quality mean is reported, and an arm with an unscored failure retains `overall=null`.
The control and staged arms are descriptive exploratory measurements, not a causal WebAgent
reproduction or a statistical superiority claim.

A fair follow-up may compare S with `resume=0` and `resume=1`, but that is a separate registered
measurement. Do not add variants after seeing outcomes.

## Reuse of existing APIs

- `AgentLoopRuntime` / `HermesSessionRuntime`: keep the model/tool boundary and per-invocation
  `ModelProfile` `UsageLedger`; add stage prompts and a controller-owned stage wrapper rather than
  changing tool semantics.
- `SessionTranscript`: use `set_session_path`, `_initial_messages`-compatible loading, and existing
  redaction/bounded persistence for same-attempt continuation. Any transcript projection used in a
  checkpoint must be a digest/size summary, never raw history in the manifest.
- `AgentLoopRuntime.set_event_sink`: collect typed model-turn/tool-result events for checkpoint timing
  and diagnostics; event data is bounded and non-authoritative.
- `AgentLoopRuntime.process_info`, `cancel`, and the existing process observer: stop a stage at its
  reserved deadline while preserving the aggregate ledger and checkpoint state.
- `EffectTrialRunner`: retain suite/public projection checks, receipt parsing, one-start guards,
  harness gating, private path isolation, and exact extractor/evaluator invocation. The staged
  controller only changes how the subject process is scheduled.
- `RecoveryPolicy`: use its deterministic, non-executable proposal model for an interrupted run;
  a recovery proposal can authorize the controller to resume, but cannot itself execute a resume or
  change a budget.
- Existing atomic JSON/hash helpers and subject diagnostics: extend bounded typed projections instead
  of adding a second receipt or score path.

## Acceptance criteria

1. Offline tests reject malformed, out-of-order, duplicated, cross-run, symlinked, over-budget, and
   digest-mismatched checkpoints without invoking a model or private harness.
2. A simulated stage interruption resumes exactly once with unchanged run id, attempt id, source,
   request, model/profile, aggregate usage, and ceilings; a second resume is rejected by the guard.
3. A staged subject that writes a complete candidate but no valid receipt remains unscored; a valid
   receipt with an unchanged public projection enters the existing harness boundary only once.
4. Master artifacts, checkpoints, diagnostics, and transcripts contain no baseline score, private
   evaluator content, credentials, or raw private paths; bounded errors remain redacted.
5. Control and staged manifests freeze identical case/public/input/model identities and aggregate
   limits before any model request. All failures, null scores, and unresolved outcomes remain in the
   fixed denominator.
6. Existing Feature 068 effect-trial, receipt, validity, resume, and scoring tests remain green; no
   old campaign files or historical manifests are rewritten.
7. A post-implementation dry run proves the two-arm protocol and timeout cleanup without a provider
   call. Real execution is a separately registered action.

## Risks and limitations

A master stage can consume useful budget or anchor the model to a poor plan; staged results may be
worse even when checkpointing works. A checkpoint preserves artifacts and context but cannot recover
provider-side hidden state. Session transcript replay may increase input tokens, so usage must be
measured from the same ledger and bounded. One case/one attempt per arm cannot estimate success
probability. Historical WebAgent duration and cache telemetry are descriptive only; they do not define
Lunar's configuration or prove that a staged arm reproduces WebAgent.
