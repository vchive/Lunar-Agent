# Plan

Create a small output-publication module used only by evolved output promotion. Stage immutable
numbered blobs and a strict bounded journal under the parent workspace. A parent-wide advisory
flock serializes this module's publishers. No-clobber hard links from stage to final destinations
prove ownership for rollback; existing identical destinations are reused and never removed.

The journal binds parent/child/owner, complete output projections, original existence and staged
file identities. SQLite records the journal SHA-256 together with the existing promotion event in
one BEGIN IMMEDIATE transaction using synchronous FULL. Recovery first verifies the whole journal,
stage, files and database evidence, then either confirms commit or rolls back uncommitted links.
An immutable rollback acknowledgement makes repeated recovery explicit. Keep journal/stage files.

Integrate recovery before terminal marker replay in LocalController. Do not convert a missing
terminal marker into successful materialization and do not replay the candidate. Existing 085
identity validation and missing-execution-marker refusal remain authoritative.

## Alternatives and complexity

SQLite-only rollback cannot undo files; file-by-file compensation without a journal loses ownership
after process exit. Replacing the entire output directory would replace existing parent outputs
and breaks path ownership. A journal plus no-clobber links is the smallest complete protocol for
the current immutable-output rule. No new dependency, service or schema migration is needed.

## Verification

Use offline multi-output fixtures and injected filesystem/database failures, including process
exit after the first link and after commit. Full repository regression plus static and sealed-file
checks must pass. Known visibility, terminal marker and execution uncertainty limits are explicit.
