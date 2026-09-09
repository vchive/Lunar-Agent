# Tasks: Budget-Aware Candidate Preservation

- [x] T064-01 Record design and failing deterministic/regression fixtures.
- [x] T064-02 Preserve complete candidates with atomic write_file replacement.
- [x] T064-03 Propagate context-local command deadlines and normalize timeout streams.
- [x] T064-04 Add transient profile budget guidance and subject authority regression.
- [x] T064-05 Complete focused/full checks, review, and handoff.

Failure-first evidence: 12 budget/tool cases initially gave 10 failures and 2 passes; the first 8
atomic-write cases gave 5 failures and 3 passes. Two HTTP profile cases failed before guidance was
implemented; four legacy/isolated cases passed. The preserved-candidate/no-scoring end-to-end test
already passed as a compatibility guard. Two extra interrupted-write cases complete 29 new cases.

Final checks: 170 targeted tests and all 667 repository tests passed (full suite 31.94 seconds).
Ruff, compileall, quiet build, Specify prerequisites, and diff checks passed. Independent review
found no blocking defect, with 157 relevant tests passing. Existing intentionally timed-out HTTP
fixtures may log a disconnected response; this is not a failing test or external network request.

No real provider call, WebAgent run, company-platform query, or change to any frozen campaign.
Generated scripts must implement their own incremental atomic output; this feature supplies model
guidance and the existing write_file mechanism, not automatic multi-file checkpointing or resume.
