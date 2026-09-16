# Validation

94 new offline tests cover:

- 34 contract/schema, capability partition, helper/report bounds and large evidence cases.
- 25 independent evaluation cases: no harness on source failure, no override of output failure,
  original source rechecks, canonical sidecar reconstruction, record downgrade and tampering.
- 33 portable delivery cases: exact source bytes, forged pass, new protocol downgrade, missing
  contract/evidence, opaque legacy compatibility, 166-file capacity and evidence above 128 KiB.
- 2 automatic CLI scenarios: one-file score 9 rejected; two-file scores 2/6/7 admitted; final 7
  delivered; both terminal resume commands retain all calls, files/inodes, events and one copy.

The evaluation and delivery implementations were delegated separately, and the automatic CLI
tests were written independently against the full flow. Review findings were fixed: failure
reports cap their 32 entries while full evidence retains all 64 constraint outcomes; pure evidence
helpers reject unsupported mixed requirements; the 256 KiB evidence limit propagates through
inspection and delivery; a distinct portable protocol prevents partial source evidence downgrades
while legacy opaque contracts stay readable. No additional approval or retry workflow was added.

Focused bundle/compiler/recovery regression: **277 passed in 38.65s**, JUnit no failures/errors/skips
(`/private/tmp/lunar119-focused.log`, `/private/tmp/lunar119-focused.xml`). Source delivery plus
existing controller/parent-delivery regression: **78 passed**. Post-review source/schema/automatic
cases: **61 passed in 6.55s**. These checks overlap and are not additive coverage totals.

Existing 112 subprocess quickstart passed: independent scores 1,2,6,7, best 7; terminal resume
retains contract/compiler/auditor/Agent/candidate counts 1/1/1/4/4 and one delivery copy. Log:
`/private/tmp/lunar119-quickstart.log`. The source-aware CLI scenario additionally observes four
candidate executions and only three output-harness calls, because the one-file proposal fails
the local source requirement. Compiler/auditor probe processes are separate from candidate scoring.

Final full regression: **5912 passed, 1 skipped in 364.74 seconds**, JUnit zero failures/errors.
Logs: `/private/tmp/lunar119-full.log` and `/private/tmp/lunar119-full.xml`. All 14 implementation/test
files remain identical to the SHA-256 values captured before that run; no product/test edits
followed it. Ruff, compileall, installed CLI, Specify, 120 local documentation links and diff checks
passed. Historical 113/115/117 and older frozen measurement directories are unchanged. Verified
work and handoff are committed/pushed under the user's standing instruction.

No real provider call, external framework execution, old slot retry or private-response replay.
The check proves declared lowercase .py file count only, including empty files. Input use,
helper imports, semantic usefulness, Python syntax and runtime dependencies remain unverified.
Source/execution declarations without a supported checker remain unsupported. Portable inspection
without an externally pinned expected digest establishes consistency, not authenticity against a
complete coherent replacement of all materials and identities.
