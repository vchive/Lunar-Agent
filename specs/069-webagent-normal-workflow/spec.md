# Feature 069: WebAgent-Normal Workflow Checkpoints

**Created**: 2026-09-09  
**Branch**: main  
**Status**: In progress (opt-in subject integration implemented; measurement pending)

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

1. **Master** receives the same public request and tools, returning strict JSON with `plan` and
   `expected_paths`. The controller validates and writes a bounded `workflow/master.json`
   containing the request digest, workspace identity, a short ordered build plan, expected deliverable
   paths, and a plan digest. It may inspect public files and formulate the approach; it may not run
   the private harness or write a subject receipt.
2. **Build** starts only after the master checkpoint passes local schema and workspace-boundary
   validation. It receives the master plan and the same public request. It implements the candidate,
   runs permitted public/local checks, and must atomically preserve a complete candidate before
   expensive refinement.
3. **Checkpoint** is written at one scheduled cooperative build boundary and at final build readiness. It records only
   typed control data: stage, workspace tree digest for declared paths, transcript digest, usage
   snapshot, tool-step count, and a monotonic checkpoint number. It contains no private results and is
   never treated as a receipt.
4. **Resume** continues within the same subject process only after a typed `StageBoundary` at the
   end of a complete, durably persisted tool round. The fixed policy triggers at the first clean
   boundary after `build_seconds`, or after an optional fixed round count. The original live ledger,
   paired transcript, candidate digests and aggregate deadline must still match. Resume is at most
   once and cannot accept a replacement prompt or timeout.
5. **Delivery** returns the final runtime result to `run_subject_adapter`, which revalidates the
   public projection and creates the unchanged normal-mode receipt. `EffectTrialRunner` validates
   that receipt before invoking its existing exact harness; workflow readiness grants no authority.

The initial implementation supports **one master followed by build and at most one cooperative
continuation in the same process**. Provider timeout/error, unavailable usage, rejected budget,
missing output and failed transcript persistence are terminal subject failures. Existing candidates
remain on disk, but a failure does not manufacture a checkpoint or a receipt. A new runner or adapter
invocation cannot restart a nonempty workflow. Recovery after process death is deferred until a
protocol can account for provider requests whose consumption was never returned.

### Resource accounting

The staged arm and its monolithic control arm use identical aggregate ceilings. The master and build
stages receive reservations for scheduling only; unused reservation returns to the same aggregate
ledger. A stage cannot borrow beyond the aggregate cap, and a resume cannot reset accepted or
observed usage. `StagePolicy` freezes positive `master_seconds`, `build_seconds`, and
`reserve_seconds`; their sum must leave room inside the aggregate ceiling for resume. Master has a
bounded invocation timeout. Build's slice is cooperative, checked between completed tool rounds;
build and continuation requests use the remaining aggregate time minus the finalization reserve.
The reserve is never added to the budget. An in-flight request or tool can consume the remaining
window before the next cooperative boundary, in which case no continuation is authorized. Optional
`checkpoint_after_rounds` is a fixed policy input, not an outcome-dependent retry. Actual experiment
values remain unregistered until T069-06.

Shared-ledger responses report cumulative tokens, cost, model identity and interaction turns across
master/build/resume. Rejected response usage is latched as failure evidence; unknown consumption
cannot be repaired by later samples. Ordinary calls still allocate a fresh ledger per invocation.

Stage prompts are protocol text, not an evaluator. They must say to save a complete candidate early,
keep output paths stable, and leave time for atomic writes. They must not contain baseline scores or
private harness details.

## Durable records and invariants

Each staged attempt has a controller-owned record under its attempt workspace:

- `workflow/config.json` — frozen explicit manifest and stage reservations.
- `workflow/master.json` — bounded plan projection, request and source identity, no score.
- `workflow/checkpoints/<n>.json` — typed checkpoint projections; write with temporary file then
  replace; monotonic `n` and no overwrite of an existing checkpoint.
- `workflow/state.json` — stage state machine and aggregate ledger state, updated atomically.
- `workflow/master-transcript.jsonl` — separate planning history.
- `workflow/session-transcript.jsonl` — bounded active build history with native tool pairs.
- `workflow/transcript-<n>.jsonl` — immutable transcript copy referenced by each checkpoint.
  Transcripts contain no evaluator evidence and are not used as validity or scoring evidence.
- existing subject receipt and diagnostic files — unchanged authority and failure semantics.

The implemented subject state sequence is `created → master_running → master_ready → build_running`
then either `build_ready`, or `checkpointed → resuming → build_running → build_ready`. Typed checkpoint
and resume methods own those transitions; direct or repeated state transitions are rejected. Master
usage is persisted before starting build. Runtime failures use existing subject diagnostics; the last
workflow state is partial evidence, not a claim of successful termination. `harness_pending` is not
reachable through this subject controller; evaluation remains entirely with `EffectTrialRunner`.

A checkpoint is accepted only when all of the following hold:

- run/attempt id, source SHA, suite/case identity, request digest, model/profile digest, and total
  ceilings match the immutable manifest;
- checkpoint number and stage transition are valid and prior state is present;
- every declared path is confined to the subject workspace, regular, and free of symlink escapes;
- usage is a complete typed snapshot or explicitly marked unavailable; unavailable usage never becomes
  zero and cannot extend a ceiling;
- the checkpoint digest is recorded before a cooperative boundary is considered resumable.

The explicit config is supplied through `run_subject_adapter(workflow_config=...)` or
`effect-subject --workflow-config PATH`. It binds the actual request digest, public case/benchmark,
profile digest and effective limits before the first model request. Run/attempt labels and the source
SHA are explicit caller assertions, retained unchanged; measurement registration must independently
verify their provenance. The normal request and receipt schemas are unchanged.

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
- `AgentLoopRuntime.StageBoundary` and `InvocationDiagnostics`: pause only at complete durable tool
  boundaries. No assumption is made that provider HTTP cancellation reports complete usage.
- `EffectTrialRunner`: retain suite/public projection checks, receipt parsing, one-start guards,
  harness gating, private path isolation, and exact extractor/evaluator invocation. The staged
  controller only changes how the subject process is scheduled.
- Recovery proposals and external process restart remain deferred; neither can bypass the live
  ledger and single cooperative continuation guard.
- Existing atomic JSON/hash helpers and subject diagnostics: extend bounded typed projections instead
  of adding a second receipt or score path.

## Acceptance criteria

1. Offline tests reject malformed, out-of-order, duplicated, cross-run, symlinked, over-budget, and
   digest-mismatched checkpoints without invoking a model or private harness.
2. A simulated cooperative stage interruption resumes exactly once with unchanged run id, attempt id, source,
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

The current offline integration exercises the real AgentLoop and subject adapter with deterministic
provider responses, plus the existing trial gate with a fixture harness. This is not an exact-harness
measurement or evidence of improved solution quality. Static path replacements and symlink escapes
are rejected at control/transcript access; these filesystem checks are not a sandbox against arbitrary
concurrent native code.
