# Plan

Add a final-materialization-specific launch module. A persistent
`evolution/.materialization.lock` uses nonblocking flock across the complete controller phase.
The lock is separate from the attempt directory and the narrower Feature 088/089 publication
locks. Existing contract/candidate identity checks run before and after acquiring the child lock.

Write `evolution/materialization/launch-intent.json` through a synced temporary file and no-clobber
link, with the source copy and directory chain synced before launch. Register a deterministic
child `materialization_launch_intended` event using a FULL-synchronous transaction. The event
binds the exact canonical intent digest and size. Store exposes exact read-only inspection and
a modern-evidence probe; no table migration or dependency is required.

The controller observes launch evidence before any recovery mutations, then permits only fully
validated cached or explicitly prepared terminal results. If none exists, existing execution
gates retain their refusal and any launch intent additionally prevents cleanup and execution.
New launch preparation occurs only after pre-execution validation. Its exceptions escape without
fabricating a terminal failure; an exception after authorization with no execution result is
unknown. Execution artifacts/events remain prerequisites for terminal publication.

## Alternatives and complexity

PID checks cannot prove that a process never ran and are unsafe after PID reuse. A marker written
after Popen leaves the same crash gap. Reusing the terminal publication lock does not protect the
earlier absence checks and cleanup. One persistent lifecycle lock, one bounded intent and one
digest-bound event are sufficient to prevent protocol-controlled relaunch without introducing a
process supervisor or changing the generic evolutionary runner.

## Validation

Tests use local deterministic candidates and controlled subprocess exits. A real candidate writes
a counter and the controller exits before publishing execution evidence; repeated resume must
leave the counter and attempt intact with zero additional runner calls. Concurrent callers must
observe the busy error and later reuse the one result. Historical sealed 051/074/076/078/082 files
and earlier validation counts remain unchanged.
