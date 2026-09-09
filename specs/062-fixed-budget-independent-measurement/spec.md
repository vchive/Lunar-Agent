# Feature Specification: Fixed-Budget Independent Measurement

**Branch**: `main`

**Created**: 2026-09-09

**Status**: Complete

## Goal

Measure Lunar with a weaker historically recorded solver model while treating unfinished and
invalid attempts as valid observations. The experiment must not be rerun until success, relabel an
unmatched baseline, or change its denominator after seeing outcomes.

## Scope

This feature is an SDD and machine-local experiment protocol. It adds no product runtime code and
does not relax the comparative `EffectTrialRunner` model guard. Existing validated subject and exact
private harness adapters are reused; generated manifest, slot records, and summary remain ignored
local evidence under `.lunar/`.

The frozen campaign has exactly two new normal-mode attempts for `supply_chain_inventory`, using
`glm-5.1`, the existing profile, the existing prompt/adapter, 40 tool steps, a 900-second subject
timeout, and a 200,000-token ceiling. The earlier GLM timeout is an exploratory pilot and is excluded
from this campaign denominator.

## Contract

The manifest freezes suite/case/public ledger and harness digests, model/profile, extractor model and
SDK, runner/source digest, mode, budget, prompt variant, and planned attempt count. Each slot is
immutable once started and moves through `not_started` → `running` → `completed`, `failed`, or
`safety_aborted`. A process nonzero exit is recorded conservatively and does not infer a diagnostic
cause; `process_terminated`, exit code, and `process_success` remain separate fields.

Each attempt records subject process/receipt state, advisory Feature 061 diagnostic fields, harness
process/receipt state, extraction/evaluation state, score fields, terminal outcome, and SHA-256 links.
Subject receipts carry no scores. Unknown usage and absent scores remain `null`; placeholder zero
values from an incomplete or evaluator-error harness are not valid quality or overall scores.

The primary valid-solution rate is `valid_attempts / planned_attempts` only after every slot reaches
a terminal state. Conditional rates use their explicit stage denominator. Quality and overall score
summaries include their sample count and only evaluator-completed valid observations. No baseline
delta, breakthrough, WebAgent parity, or statistical superiority is emitted.

## Acceptance

- Manifest drift, pilot mixing, source drift, or slot replacement is rejected before model execution.
- Exactly two new slots are started; a failure occupies its slot and is not retried or replaced.
- Summary counts reconcile with durable slot records; unresolved slots do not become failures.
- Subject receipt carries no score; incomplete/error harness receipts leave the slot unscored and the
  summary emits `null`, never a fabricated zero. Evaluated-invalid and evaluated-valid are separate.
- The exact harness remains the only score authority and private evaluator content is never given to
  the subject.
- A local audit can reproduce the summary from the manifest and immutable slot records without model
  calls. No product code changes are required.
