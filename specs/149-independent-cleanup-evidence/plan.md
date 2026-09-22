# Implementation plan

1. Define the canonical cleanup-v1 parser/builder and a redacted audit projection with fixed
   fields, bounded integers, digest binding, and conservative outcome rules.
2. Extend native execution evidence with an optional no-follow `cleanup.json` and a completion
   descriptor link. Keep old v1 completion bytes valid and keep missing cleanup unknown.
3. Capture runner observer/release identities and an independent process-group absence probe only
   after the process boundary; callback failures cannot turn cleanup into success.
4. Reuse the cleanup parser in the native acceptance auditor and allow the optional file in the
   one-slot auditor. Preserve inode/device and race checks.
5. Add provider-free tests for success, failed/unknown cleanup, descriptor tampering, copied or
   inode-replaced evidence, denied probes, post-cleanup crashes, and old-record compatibility.
6. Run focused tests, related execution/evaluation/audit regressions, Ruff, compileall, SDD/link
   checks, then commit and push. Do not start a real provider attempt in this slice.
