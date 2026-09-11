# Feature 082: HTTP Deadline Fixed Measurement

**Created**: 2026-09-11
**Status**: Completed: both slots terminated; independent final acceptance and scoped process checks passed.

## Objective

Measure whether the current GLM-5.2 staged runtime completes Master→Build delivery on the two
previously selected high-baseline cases after integrating079/080/081. Freeze product source
`e36b103fd6fc4a64304d16ae446e0383dab0a8a8`. The current product adds safe terminal diagnostics,
request timing and an absolute HTTP transport deadline relative to078. This is a descriptive
measurement of that integrated source, not an isolated causal test of the deadline or a claim
about why either sealed078 attempt timed out.

## Frozen protocol

- Exactly two fresh staged S attempts: sheet_metal_nesting and china_post_pickup_optimization,
  one each, wave [[1, 2]], concurrency2, campaign `.lunar/real-eval-glm-5.2-http-deadline-20260911`.
- Keep078's authorized GLM-5.2 profile, endpoints, public/private inputs, exact harness, extractor
  and dependency identities. Use the existing local CC Switch loader only for registration
  configuration checks and the actual launch. Never print credentials or query a provider to test
  connectivity. Do not run WebAgent or access the company platform.
- Master1200, cooperative Build2400, reserve120, checkpoint_after_rounds32; shared subject5400
  seconds/200 tool steps/8,000,000 tokens and at most one same-process cooperative continuation.
  Outer subject5430, harness3630 and slot9300 seconds. These are inherited limits, not evidence
  that they are sufficient for every case; Build's final request may consume remaining shared time.
- Every attempt occupies its registered slot. No retries, replacements, candidate replay, score
  backfill, post-launch source/prompt/budget edits or model upgrades.

## Acceptance and evidence

1. Independently check the complete source tree, including the new isolated HTTP helper, against
   the frozen commit. Verify all new execution/report/test files, transitive helper pins, historical
   anchors, inputs, actual harness/dependency versions and fresh unstarted slots before dispatch.
2. Run guarded offline registration, lifecycle, v4 diagnostic and deadline fixtures without provider
   access. Commit and push the final manifest, mirrored preaudit/dry-run evidence and frozen scripts
   before the unique launch. A failed launch cannot be silently repaired into a replacement slot.
3. Preserve native plan acceptance, Build entry, optional checkpoint/resume, receipt and harness
   evidence. A plan, partial candidate or diagnostic cannot authorize scoring. Only the original
   EffectTrialRunner and exact harness define validity and scores, including valid scores above1.
4. Project only validated, request-bound terminal diagnostics from the frozen native schema: fixed
   stage/code, nullable HTTP status, typed model failure and optional v4 request observation.
   Keep unknown data null; do not infer per-request data from an outer kill or prior records.
   Reporting must tolerate missing/invalid diagnostics without promoting them to scoring authority,
   and must not expose raw prompts, response bodies, exception text, credentials or candidate content.
5. Denominator stays planned2. Unstarted/unterminated slots remain unresolved until durable terminal
   evidence exists. Report started/terminal/plan/Build/receipt/harness counts, observed valid count
   and scored samples separately; exact Master duration and full failed usage/cost remain unknown.
6. After both slots terminate, reconcile the native summary, independently audit evidence hashes
   and visible owned processes, then seal results. Preserve074/076/078 files byte for byte; never
   rerun their old live-source audit against current code or change old manifests to pass it.

## Limits

No product implementation or schema migration belongs to082. The HTTP deadline covers local
transport, with startup and cleanup overhead; it neither guarantees hard realtime complete()
return nor stops remote generation/billing. macOS local fixtures do not establish Linux behavior.
Two uncontrolled attempts cannot prove reliability, WebAgent parity or improvement. Historical
attempts remain context outside the denominator. Any discovered product fix must be isolated and
must wait until this campaign is sealed before integration.
