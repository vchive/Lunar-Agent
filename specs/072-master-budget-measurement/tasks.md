# Tasks: Master Budget Measurement

- [x] T072-01 Specify fixed four-slot budget-only protocol, shared limits and interpretation limits.
- [x] T072-02 Add tested per-slot registration/binding and isolated pinned execution reuse.
- [x] T072-03 Implement independent preaudit/dry-run and null-aware per-group/postrun reporting.
- [x] T072-04 Finish offline checks and independent review; freeze, commit and push registration.
- [ ] T072-05 Launch exactly once and observe all four attempts without changing frozen inputs.
- [ ] T072-06 Independently audit final native evidence/process termination, seal results and handoff.

Offline verification on 2026-09-10: full suite 1037 passed (36.16 seconds), including new runner,
per-arm audit, actual AgentLoop/staged budget fixtures and postrun tests. Ruff, Specify and diff
checks passed. Independent cross-review confirmed the pinned private module graph, native receipt
authority, fixed waves and exclusive launch, per-slot budget checks and read-only phase reporting.
Postrun review fixes cover missing successful workflow evidence, final transcript/checkpoint
consistency, recorded usage monotonicity and disagreement between rows and group totals.
Product source and all Feature069 files are unchanged from 5c89e04. No provider call has occurred.

Final prelaunch checks: seven further regressions reject orphan slot markers/summary before launch;
Feature072 targeted set 98 passed and isolated exact-registration dry-run 159 passed across
12 scenario groups. No network/provider configuration was available to dry-run fixtures.
Independent actual prelaunch audit verified 37 source files, 92 frozen files and 13 historical
anchors, actual private case/extractor/evaluator bytes and installed harness versions.
Both reports are mirrored byte-for-byte into the fresh local campaign directory.

- Manifest SHA256: cbdb07e22b08a8944b9e80bf7f30cbd4057b931bd6128077dcf5da533834f830
- Prelaunch audit SHA256: a5e210faf369b0133c567197f4ea3a33327772ccab601251b7e72613dbbd2132
- Dry-run SHA256: 7609a3beb2aec800ad1a5e094a29cef4a8cfe2ab882b821bc10430e2f7de5801

The registration commit containing this record must be pushed before the one-shot launch.
T072-05/06 remain open until dispatch/observation and final independent audit respectively.
