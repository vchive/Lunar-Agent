# Tasks: High-Score Case Measurement

- [x] T068-01 Audit the existing high-score baseline and freeze deterministic selection.
- [x] T068-02 Prepare exact 1.10.6 public/private kits and fresh attempts without model calls.
- [x] T068-03 Adapt and verify fixed-budget runners, summarizer and launch guards.
- [x] T068-04 Independently audit and commit registration before dispatch.
- [ ] T068-05 Run two fixed Lunar slots and permitted exact harness stages to termination.
- [ ] T068-06 Audit, report per-case results, update HANDOFF and publish the record.

Pre-execution manifest SHA-256:
`3a5d7cbbf7fdbd44f023340c6079e435fc256bc68e3910fb4ad5acd47a332656`.
Product source: `01c541e714bc0d1c0ebebdb7a4dcb564c3a8dbe5`, unchanged from the previous campaign.
Frozen ledger: 35 product sources, 16 prepared attempt files, 151 historical/supporting files.
Baseline audit SHA: `83581b93438a9ad02ca97534f77556bcf2584d23bab03d07cc5d3291b6ea86a4`.

Both current local case trees reproduce the official 1.10.6 package, content and public projection
digests under the publication SDK. No historical case checkout was needed. Public projections have
three files per case; private case copies remain separate from both fresh subject workspaces.

Independent harness venv preserves all 30 previous pinned distributions and adds pandas 2.3.3,
numpy 2.5.2 and the frozen pandas dependencies. Existing compatible package files were independently
copied and SHA-verified; only missing packages were installed. Four exact evaluator/extractor script
imports and pip check passed. The old venv was not changed. Requirements/copy proof/readiness are
bound in the supporting ledger; no model call or connection probe was made during preparation.

Guarded launch --check-only, syntax and deterministic offline checks passed: model/profile/budgets,
score above one, strict validity=1, partial versus complete usage, unresolved/v1/outer failures,
per-case summaries without pooled quality, and short-process timeout cleanup. Specify and diff
checks passed. Product tests are unchanged from Feature 066's 726 passing tests.

Registered UTC: 2026-09-09T11:26:47.895175+00:00. Independent prelaunch audit passed: 35 product
files and 35 implementation git blobs, 16 inputs, 151 historical/supporting files, 24 publication SDK
git blobs, two independent official package rebuilds, six public files, 27 private package files and
37 installed harness package versions. Both attempts have no start/results/receipts/bytecode files.
Audit SHA: `2e3f5e69ec9e8b9e2327125c6b3252cc321d3fbcad4f5c53e21e7559a191e856`.
This registration commit must precede model dispatch; the immutable manifest does not change at launch.
