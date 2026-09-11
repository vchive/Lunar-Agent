# Tasks: Failed Model Request Timing

- [x] T080-01 Review078 evidence and current HTTP/diagnostic boundaries; define the smallest observation contract.
- [x] T080-02 Approve spec/plan, compatibility and failure-authority limits before implementation.
- [x] T080-03 Add failure-first timing/phase, legacy and hostile-evidence regressions.
- [x] T080-04 Implement request-local typed timing and strict diagnosticv4 with safe fallback.
- [x] T080-05 Verify native failures preserve no-retry/no-receipt/no-harness/unknown-score behavior.
- [x] T080-06 Independently review; run full regression, Ruff/Specify/diff and sealed-evidence checks.
- [x] T080-07 Update HANDOFF and verification notes; commit/push the completed feature.

The fixed078 result remains valid0/2, and079 did not participate in it. No real invocation or new
measurement is part of this feature. Product implementation owner is diagnostic_design; root owns
specification, integration review, documentation and commits. Reviewers are read-only.

Initial failure-first verification:72 new scenarios ran on the preimplementation code,
48 failed /24 passed in0.63 seconds. Failures identified absent timing/v4; fallback and success
compatibility cases already passed. The implementation uses a module-local monotonic reference
so deterministic clock fixtures do not replace other modules' budget clocks.

## Final verification (2026-09-11)

The new module contains76 scenarios. Implementation verification passed391 focused/native
normal/deep/staged/runtime/budget/diagnostic tests in20.02 seconds. The independent reviewer then
passed238 timing/model-evidence/subject/runtime tests in13.16 seconds and found no blockers.
Root ran the full main suite once: **1614 passed in39.79 seconds**. Full src/tests Ruff, Specify080
prerequisites and diff checks passed. All tests used loopback or deterministic fixtures; no provider
environment, private harness, WebAgent run or historical candidate execution was needed.

Review verified same-object bare rethrow and originalcause depth, actual timeout forwarding,
singleurlopen/read behavior, successwire/defaults/fallbacks, invalid clocks and constructors,
no cross-call observation reuse and no cross-exception evidence mixing. Version4's extra fields
preserve the4096-byte request-bound publication/collection contract. Native failures retained
no-retry/no-receipt/no-harness/unknown-score behavior; a later deep failure preserves prior scores.
The only changes in the079 test module are four actual-complete version assertions and one test
name; manually constructedv3 and malformed/foreignv1 fallbacks remain pinned.

Root compared all Git-sealed078/076/074 files to their respective seal commits:205/105/68 files
remain byte-for-byte unchanged. The frozen078 valid0/2 result and unknown full failure usage/cost
are unchanged. README and HANDOFF explain the new terminal observation and urllib timeout limits.
Feature079's stale spec status was corrected to completed; no historical evidence was rewritten.

Remaining work is separate from080: decide and specify absolute HTTP request deadline behavior
using offline slow-response fixtures, then use a new fixed registration for any further real
measurement. Do not modify/reopen078 or infer its last-request timing from this instrumentation.
