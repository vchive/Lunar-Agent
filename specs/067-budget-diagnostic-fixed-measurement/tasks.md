# Tasks: Budget Diagnostic Fixed Measurement

- [x] T067-01 Prepare two fresh slots and freeze protocol/source/input identities.
- [x] T067-02 Verify local readiness, strict evidence summaries and independent registration audit.
- [ ] T067-03 Commit registration, dispatch each slot once and retain all outcomes.
- [ ] T067-04 Audit and aggregate actual outcomes without promoting partial usage or claims.
- [ ] T067-05 Update handoff/results and publish the completed record.

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
will be committed before either slot starts; outcomes will be recorded separately from the manifest.
