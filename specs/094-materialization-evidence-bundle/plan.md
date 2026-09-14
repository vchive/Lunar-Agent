# Plan

Reuse `diagnostic_snapshot()` and `diagnose_materialization()` only. Add a pure sanitizer that
converts snapshot rows to fixed metadata/hash envelopes. Build canonical JSON, enforce the 256 KiB
bound, and write it with no-clobber O_EXCL to a user-selected destination outside both workspaces.
The CLI dispatches before `_config()` exactly as 093 does. No database schema or runtime changes.

## Complexity and alternatives

A second recovery state machine is rejected; the bundle only preserves 093 observations. Copying
raw events risks secrets, goals and commands, so values are replaced by payload digest/size. A
sibling temporary file and fsync provide durable export without overwriting an existing review.
