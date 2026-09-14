# Validation — 2026-09-14

- Evidence bundle focused tests: 13 passed in 3.84s.
- Coverage includes stable export, deterministic bytes, sensitive-data redaction, destination
  no-clobber and symlink/workspace/missing-source rejection, lock contention, source snapshot
  preservation, WAL-backed state and CLI pre-initialization dispatch.
- `ruff check src tests`, `compileall -q src tests`, and `git diff --check`: passed.
- Final full repository regression: 3599 passed in 205.44s.

The bundle contains only the diagnostic report and allowlisted identity/hash envelopes. It is not
recovery authority, does not authenticate writers or identify processes, and may return unavailable
when source evidence changes during capture. No real model, provider, WebAgent or remote campaign
was run.
