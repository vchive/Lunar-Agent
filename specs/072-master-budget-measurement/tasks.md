# Tasks: Master Budget Measurement

- [x] T072-01 Specify fixed four-slot budget-only protocol, shared limits and interpretation limits.
- [x] T072-02 Add tested per-slot registration/binding and isolated pinned execution reuse.
- [x] T072-03 Implement independent preaudit/dry-run and null-aware per-group/postrun reporting.
- [x] T072-04 Finish offline checks and independent review; freeze, commit and push registration.
- [x] T072-05 Launch exactly once and observe all four attempts without changing frozen inputs.
- [x] T072-06 Independently audit final native evidence/process termination, seal results and handoff.

Offline verification on 2026-09-10: full suite 1037 passed (36.16 seconds), including new runner,
per-arm audit, actual AgentLoop/staged budget fixtures and postrun tests. Ruff, Specify and diff
checks passed. Independent cross-review confirmed the pinned private module graph, native receipt
authority, fixed waves and exclusive launch, per-slot budget checks and read-only phase reporting.
Postrun review fixes cover missing successful workflow evidence, final transcript/checkpoint
consistency, recorded usage monotonicity and disagreement between rows and group totals.
Product source and all Feature069 files are unchanged from 5c89e04. At that prelaunch point no
provider call had occurred.

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

Launched once after pushing registration commit 09a7ea997df71e31bcdccaeba20f9140aa630b94 at
2026-09-10 13:09:00 +0800. Dispatcher PID/PGID69681; first-wave workers69812/69813 and subjects
69814/69815 observed. Both initial stages were master_running, no plan/Build/score yet; wave2
waits for both wave1 slots to terminate. Initial postrun audit passed with 169 evidence hashes,
complete=false. The launch/process snapshots and observation are saved separately from frozen
registration. Never rerun --launch or unstarted-only checks; source/scripts/tests/inputs stay frozen.

Final closure on 2026-09-10: all four subjects and outer slots terminated. Both300-second slots
timed out (sheet300.229s model/timeout; postal300.123s runtime/timeout). Both1200-second slots
returned prose plus one JSON fence and failed before Master acceptance (postal240.183s;
sheet841.108s). Both budget groups valid0/2, no plan/Build/resume/receipt/harness; scores and full
failed usage/cost stay null. Precise Master duration stays null. No retry or replacement occurred.
Final independent audit verified233 evidence hashes; scoped process check found no known PID,
durable worker group member or visible072-associated argv/cwd process. Original markers did not
record subject child IDs, so complete historical descendant coverage is not claimed.
The read-only watcher session74763/PID70063 exited0. All37 source/92 frozen/13 historical file
hashes were verified unchanged before sealing. Product integration is permitted only after this
final evidence is committed and pushed, preserving the old manifest unchanged.

- Final audit SHA256: 2973625674cc0056e8891e384b6feeb021ba1174b217e10d3c633cf23232480f
- Final report SHA256: 10e6399291146c75e4abad942c908af6bbad652f3a5f999522c17fda6f0c15b4
- Native summary SHA256: 297b2472807a7f11259985edea5c8d415e0b7fccfe13b01e86fc2c7731ef1d4e
- Process check SHA256: 6c4adfdaed63da5980891b5a98a09cbb08053de866c5e8c9a1ad0067bc80ceb0

Feature073 was independently implemented in an isolated worktree and passed1147 offline tests.
Its pure parser accepts both observed final responses in memory, with no model/candidate/receipt/
harness execution; this is follow-up compatibility evidence only and never changes072 outcomes.
