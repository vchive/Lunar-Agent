# Feature Specification: Budgeted real multi-file acceptance

**Created**: 2026-09-18
**Status**: Implemented; preregistration and real acceptance pending
**Input**: Continue the next real multi-file acceptance using specification-driven development.

## User Scenarios & Testing

### US1 — Observe one complete real delivery (Priority: P1)

The user needs evidence that the current system can turn a small natural-language goal and input
into a feasible complete multi-file project, independently score it and deliver it to its parent.
The local fixture already succeeds, but no real automatic multi-file end-to-end success is verified.

**Independent test**: Run one newly registered attempt with fixed conditions and report success or
failure, including preparation, delivery and cleanup evidence. An unsuccessful attempt remains a
valid measurement result and must not be replaced.

**Acceptance scenarios**:
1. Given frozen, committed and pushed conditions and an unused campaign root, when the attempt
   starts, at most one slot is consumed and all model requests share its fixed limits.
2. Given a completed delivery, when it is independently inspected, its complete source, registered
   input, output and scoring evidence agree; at least two Python source files are present.
3. Given failure, timeout or missing evidence, when results are reported, the failed denominator
   remains one and unknown quality or usage remains unknown.

### US2 — Understand preparation timing and failure (Priority: P2)

The user needs to distinguish candidate execution limits, preparation request limits and total
preparation time, and see safe request/HTTP diagnostics without exposing private generated content.

**Independent test**: Synthetic success, request failure and preparation exhaustion produce
validated timing/policy evidence, preserve accounting, and never add another attempt.

**Acceptance scenarios**:
1. A preparation request can receive up to 900 seconds while normal requests and candidate
   execution retain 600 seconds; remaining preparation or campaign time may reduce those limits.
2. Prepared evaluator checks use all eight predeclared holdouts only while campaign time remains.
3. A request failure retains valid typed diagnostics and stops further model admission. Public
   HTTP status describes observed exchanges; it does not infer provider work or unknown usage.

### US3 — Reinspect evidence without rerunning work (Priority: P3)

**Independent test**: Summarization reads retained evidence without calling a model or executing
generated code, preserves the original evidence bytes, and writes one new public report inventory.

### Edge cases

- Contract clarification, malformed responses, unsupported constraints or missing evaluator.
- Request timeout before response headers, partial response, missing usage, budget exhaustion.
- Corrupted policy/start/failure evidence, input drift, invalid output or source file count.
- Interrupted worker, unverified cleanup, pending request, partial preparation or delivery.
- Changed product, uncommitted registration, reused campaign root, or changed provider identity.

## Requirements

- **FR-001**: Register product `15710bd420d70aa07a06ee9dd4329dfbf1912b2b`, one new campaign
  `acceptance134-glm-5.2-budgeted-multifile-20260918`, and one `attempt-001` before real requests.
- **FR-002**: Retain Feature 131's task/input/holdouts/provider/population conditions: input
  `{"limit":3}` plus newline, maximize integer output value in `[0, limit]`, minimum two Python
  source paths, GLM-5.2, population 2, offspring 1, islands 1, rounds 1, stagnation 3, seed 129.
- **FR-003**: Fix normal request and candidate execution limit 600 seconds, preparation request
  limit 900 seconds, preparation wall limit 1860 seconds, campaign wall limit 2400 seconds,
  at most 20 provider requests, stop after observing 160000 tokens, and 5 seconds per holdout.
  The observed token threshold is not a provider-side token cap. No campaign retry, resume,
  replacement, response repair or fallback is allowed.
- **FR-004**: Freeze the task, provider identity, runtime, implementation/tests and prior evidence
  hashes before launch; reject any changed registration or reused slot without a model request.
- **FR-005**: Preserve the native persisted preparation policy and validate it during inspection.
  Public results include safe request diagnostics, preparation failure details and HTTP status.
- **FR-006**: Primary success requires verified feasible source-aware parent delivery. Secondary
  success requires exact agreement on all eight holdouts. Joint success also requires verified
  cleanup, completed worker and zero native/process exit. Official quality/gap require completion.
- **FR-007**: Keep prompts, captured model text, generated source, credentials and endpoint values
  private. Publish only bounded safe metadata, outputs/check results and evidence hashes.
- **FR-008**: Preserve all historical evidence. The result is a new independent denominator,
  with references to Feature 128 preparation and Feature 131 attempt; it is not a causal experiment.

### Key entities

- Registration: fixed product, runtime/provider identity, task, budgets, measurement and history pins.
- Attempt: once-only start, bounded request ledger, worker result and cleanup observation.
- Delivery evidence: complete source/input/output bindings and independent feasibility/score checks.
- Report: success denominators, known/unknown usage, safe diagnostics and retained evidence inventory.

## Success Criteria

- **SC-001**: Exactly one attempt is reported, with no replacement or hidden retry.
- **SC-002**: Report delivery/preparation/joint outcomes out of one, and holdout matches out of eight.
- **SC-003**: Every admitted model request has a retained start and either a finish or explicit
  pending status; missing usage never becomes zero or complete total usage.
- **SC-004**: Offline success, failure, exhaustion, corruption and read-only recovery checks pass
  before registration is pushed. Retained evidence size/hash inventory is independently verified.
- **SC-005**: This measurement is complete when its single outcome and limitations are reported;
  product end-to-end acceptance passes only if primary and joint success are both one.

## Assumptions and scope

The existing configured provider and synthetic task are authorized by the instruction to proceed
with the proposed next real acceptance. Preparation receives more time per request while overall
wall/request-count/token ceilings remain unchanged. This does not diagnose remote latency or
prove Feature 133 caused an outcome. File count does not prove helper use or input reading;
eight integer holdouts do not prove general evaluator correctness. No WebAgent run, external
framework, product-code change, stronger sandbox or global cancel/detached implementation is included.
