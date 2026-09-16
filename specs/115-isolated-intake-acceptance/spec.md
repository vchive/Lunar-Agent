# Feature 115: Acceptance after isolated contract intake

## Outcome

Independently register and run the same two GLM-5.2 automatic multi-file tasks after Feature 114,
with product bytes fixed at `5e2568f286b709c7f8bd4c883bf654582908e736`. The completed Feature 113
campaign remains frozen at 0/2 on `c977eb4`; no old slot is reopened or replaced.

## Acceptance

1. Preserve the exact 113 task text, input objects, order, model/gateway, population settings
   (including seed 113), ceilings, task oracle and evaluator holdouts. Freeze a new manifest,
   source/runtime/helper hashes and independent attempt roots; commit and push before launch.
2. Run each task once, sequentially, without clarification answers, retries, repairs, fallback
   models or replacement slots. Preserve all planned attempts and null scores for failed tasks.
3. Use the same primary, delivery and registered-envelope completion definitions as 113.
   Independently verify successful output quality and frozen evaluator holdouts, if available.
4. Add only passive private response-text diagnostics before downstream protocol parsing. Keep
   request parameters, returned ModelTurn, model behavior and scoring unchanged. Record at most
   a 64 KiB UTF-8 prefix after credential redaction, original text size/hash, truncation and tool
   count. Diagnostics never enter model context; missing diagnostics do not alter native outcomes.
5. Report 115's fixed denominator separately from 113. This is a descriptive before/after on
   two tasks, not an isolated causal estimate or a comparison against normal mode or WebAgent.

## Fixed limits

Per task: 1200 seconds total wall time, 180 seconds per request/process, at most 16 provider
requests, a 160000 observed-token stop threshold, four tool steps per normal invocation. Use
two initial candidates plus one offspring, one island/round, stagnation 3, seed 113. No exec
tool, memory or retained Agent session. Server sampling parameters remain native defaults.
The observed-token threshold is not a hard server token cap; unknown usage and cost stay unknown.
