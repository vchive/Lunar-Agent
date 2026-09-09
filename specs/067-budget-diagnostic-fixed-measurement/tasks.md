# Tasks: Budget Diagnostic Fixed Measurement

- [x] T067-01 Prepare two fresh slots and freeze protocol/source/input identities.
- [x] T067-02 Verify local readiness, strict evidence summaries and independent registration audit.
- [x] T067-03 Commit registration, dispatch each slot once and retain all outcomes.
- [x] T067-04 Audit and aggregate actual outcomes without promoting partial usage or claims.
- [x] T067-05 Update handoff/results and publish the completed record.

Pre-execution manifest SHA-256:
`41479e3b5d97ea3e2635aea0dc1ae831b18d15bbe746e0f002163826f8553e5f`.
Registered UTC: 2026-09-09T10:12:35.139699+00:00. Source implementation: `01c541e`.

Independent prelaunch audit passed: 35 source files match both workspace and implementation git
blobs; 14 inputs, 95 historical files and all four local scaffold script hashes match. Two slots
each contain exactly seven prepared files, with no links, special files, results or start markers.
Only source implementation/diagnostic variant differs from Feature 065 identity. Profile, prompt,
model, budgets, exact harness and endpoint digests match. Readiness was refreshed locally with
SDK 0.1.81, anyio 4.15.1 and mcp 2.2.0. No provider call or connection probe was made.

The guarded --check-only launcher and deterministic summary checks passed, including partial usage,
unresolved results and v1 compatibility. Specify prerequisites and diff check passed. Registration
was committed/pushed as `9c00b88` before either slot started; observations are separate from manifest.

Both slots terminated with subject exit code 2 at 488.371 / 522.781 seconds. V2 diagnostics confirm
max_total_tokens exceeded: accepted 179567 / 198120; observed including trigger 214723 / 238712;
ceiling 200000. Both trigger_recorded=false and usage_completeness=partial. Event counts remain
11/12 and 12/13 model/tool events. Retained ordinary files: 3 / 1, metadata only, no validated solution.
No subject receipt or harness; planned=2, failed=2, valid=0, scored=0, unresolved=0. Scores and complete
failed-run usage remain null; two budget diagnostics are counted independently from complete usage.

Independent final audit passed: all 35 sources, 14 inputs, 95 history and 22 observation SHA links;
recomputed summary matches publication exactly and registration commit precedes launch. No matching
runner/subject/harness process remained. Product code stayed unchanged from its 726-test verification.

Summary SHA: `7c90a35bf958306d6d030019093f42e2e4f0ea4f0d98bb6252e4af9fb30f05cb`.
Audit SHA: `1d19768cabe8d9e9cca229f19447894842e80f7cc1c69056425ebb68a5ac1674`.
Post-measurement arithmetic SHA: `88c611c26b82033a99b0b70dca8d20e8747e594409abf08003652a277416b5af`.

Reported trigger input alone (25670 / 25488) exceeds remaining allowance (20433 / 1880). This
supports investigating context/input-budget management under a separate SDD, not asserting a
specific verbose tool, a guaranteed benefit from compaction, or a historical failure cause. No retry,
replacement, WebAgent run, platform query, raw artifact execution or retrospective score was added.
