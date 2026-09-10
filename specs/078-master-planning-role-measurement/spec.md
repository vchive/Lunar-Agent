# Feature 078: Master Planning Role Fixed Measurement

**Created**: 2026-09-10  
**Branch**: `main`  
**Status**: Draft

## Objective

Measure the real delivery effect of the Feature 077 staged Master prompt after its integration.
The only product variable is the explicit planning-role prompt in the current source. This is a
descriptive, pre-registered experiment: it does not promise that the prompt fixes the 076 timeout,
and it does not reinterpret any prior failure or score.

## Frozen protocol

- Exactly two fresh staged `S` attempts: `sheet_metal_nesting` and
  `china_post_pickup_optimization`, one slot per case, one wave `[[1, 2]]`, concurrency 2.
- Subject model and profile remain the historically authorized GLM-5.2 configuration through the
  existing local CC Switch snapshot. No provider probe, model upgrade, WebAgent execution, or
  company-platform query is allowed.
- Reuse the exact public projections, private cases, extractor, exact harness and evaluator
  bindings used by Feature 076. The subject receives no private evaluator content or old candidate.
- Keep the 076 staged limits unchanged: Master 1200 seconds, Build 2400 seconds, reserve 120
  seconds, shared subject 5400 seconds, 200 tool steps, 8,000,000 cumulative tokens, and one
  cooperative continuation at the existing checkpoint boundary. Outer subject, harness and slot
  limits remain 5430, 3630 and 9300 seconds.
- Run each slot once. A timeout, provider failure, malformed plan, partial candidate or missing
  receipt occupies its slot; no retry, replacement, prompt edit, budget change or score backfill.

## Single controlled change

The measured product source is the Feature 077 merge result. The staged Master user message states
the planning role before the original task, preserves that task verbatim as Build context, and asks
for a minimal handoff. System prompts, tool schemas and capabilities, Build/resume prompts,
deadlines, usage accounting, parsers, path/secret checks, receipt validation and exact harness
authority are frozen to the post-076 integrated source. No diagnostic enhancement is bundled into
this measurement.

## Evidence and acceptance

1. Before either start marker, independently verify the registration commit, source tree, public and
   private input digests, profile/model identity, helper closure, harness identity and empty slot
   workspaces. Record the manifest and mirror the preaudit/dry-run reports.
2. For each slot, preserve immutable observations for Master plan validation, Build entry, optional
   checkpoint/continuation, subject receipt, harness invocation/receipt, evaluator completion,
   validity and scores. A plan, local score, candidate file or checkpoint never authorizes scoring.
3. Count the planned denominator as two only after both slots reach terminal states. Keep stage rates
   explicit (plan accepted / started, Build entered / plan accepted, valid / planned). Unknown
   scores, precise Master duration, and complete failed usage/cost remain `null`.
4. The exact native harness remains the sole validity and score authority. Preserve valid scores
   above one and do not calculate pooled quality, causal deltas, stability claims or WebAgent parity.
5. Independently audit all evidence hashes, source/import identity, native record/receipt chain and
   visible process termination before sealing a report and updating `HANDOFF.md`.

## Safety and scope limits

Diagnostics are score-free and advisory. Raw prompts, provider bodies, exception text, credentials,
private evaluator data and candidate contents are not added to the campaign evidence. Existing
failure diagnostics may report fixed stages/codes and nullable HTTP status; they must not authorize
recovery, receipt creation, harness execution or a retry. Historical 069/072/074/076 attempts stay
outside this campaign denominator and their manifests and bytes are immutable.

This feature measures whether the current 077 role contract changes observed stage delivery on two
cases. It cannot establish why a provider failed, prove a timeout cause, estimate general
reliability, or establish a performance improvement from two samples.
