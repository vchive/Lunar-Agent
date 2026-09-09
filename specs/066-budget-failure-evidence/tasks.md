# Tasks: Budget Failure Evidence

- [x] T066-01 Record specification and observe failing regression tests.
- [x] T066-02 Capture typed budget snapshots without changing ledger/agent execution decisions.
- [x] T066-03 Add bounded v2 projection and strict v1/v2 collection compatibility.
- [x] T066-04 Verify normal/deep receipt, scoring, recovery and diagnostic isolation boundaries.
- [x] T066-05 Complete independent review, quality checks and handoff.

Failure-first evidence: the initial diagnostic suite gave 10 failed / 36 passed; ledger tests gave
5 failed / 11 passed; normal/deep integration targets gave 2 failed / 1 passed. Seven subsequent
diagnostic cases additionally cover oversized/invalid evidence and safe fallback. Total: 59 new cases.

Final checks: all 726 repository tests passed (30.35 seconds), as did Ruff, compileall, build,
Specify prerequisites and diff checks. Independent review found no blocking issue and separately
ran 229 relevant tests. Normal HTTP and deep process fixtures verify receipt, score and resume
authority. No external model call, WebAgent run, platform query or historical evidence mutation.

Full failed-run usage remains unknown. V2 only adds partial reported-response budget evidence for
future failures; a new preregistered campaign is required to obtain real observations with it.
