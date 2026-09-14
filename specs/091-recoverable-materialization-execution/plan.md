# Plan

Add a final-materialization-specific execution publication module and Store operations. Reuse
090's full lifecycle lock and its strict launch intent inspection. The generic runner already
publishes and syncs execution.json before returning; leave it unchanged and compare those bytes
with the returned CandidateExecution before writing any 091 preparation.

Store the bounded journal and completion receipt under
`evolution/materialization/.execution-publication/`. The journal binds the existing execution
file rather than copying or replacing it. After syncing that file and its directories, prepare
the journal and the SQLite receipt; atomically register all execution ledger rows, then publish
the completion receipt. Fixed event/artifact identities and exact read-only snapshots reject
partial registration, logical duplicates and missing modern evidence. No migration or dependency.

Insert recovery before the launch evidence execution check and before 088/089 mutation. Continue
using existing execution validation after reconciliation. A read-only modern execution check
also participates in terminal validation. Keep legacy complete records unchanged when no 091
evidence exists. Without prepared terminal bytes, execution registration alone does not authorize
output publication or terminal claims. Prepared reconciliation rejects retained downstream
output/terminal filesystem or database evidence, which proves registration already advanced.

## Alternatives and complexity

Treating raw execution.json as preparation could silently rebuild damaged historical records and
confuse runner output with controller authorization. A SQLite batch alone closes partial inserts
but cannot authorize recovery after an interrupted return. A retained prepared journal plus
post-commit receipt separates uncommitted work from damaged committed work without a supervisor
or a distributed transaction. The new protocol follows 089's explicit preparation boundary but
does not rewrite execution bytes or generalize unrelated publication modules in this feature.

## Validation

Use deterministic local fixtures, controlled SQL/filesystem faults and real child-process exits.
Recovery must retain execution bytes and a counter of one, commit exactly one artifact/event
batch, and never call the runner or output promoter. Compare full snapshots on rejected drift.
Run the quickstart and full regression, preserve historical validation counts and all 601 tracked
files under 051/074/076/078/082. No constitution exception is required.
