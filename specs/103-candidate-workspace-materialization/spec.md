# Feature 103: Candidate workspace materialization

## Problem and scope

Feature 102 verifies the declared bytes of a multi-file candidate bundle but deliberately does not
create an execution location. This feature copies those verified bytes into a newly allocated,
private workspace and defines a static execution-plan DTO for a later runner. It does not execute,
import, evaluate, admit, archive, or register a candidate.

## P1 acceptance scenarios

1. A valid two-file bundle is copied to a new workspace. Every declared destination file has the
   declared size and digest, and the result contains only a path-free file-table digest.
2. Source edits, deletion, replacement, links, FIFOs, ancestor replacement, destination conflicts,
   and destination links fail with fixed workspace errors and leave no partial workspace.
3. A plan is parsed and deeply revalidated without filesystem IO. It binds the bundle, contract,
   entrypoint, file table, runner command, limits, and explicitly supplied environment.
4. Materialization never starts a process, imports source, initializes Store/home, or writes a
   Candidate, receipt, archive, or materialization ledger.

## Frozen contract

Workspace plan schema `1` uses protocol `lunar-candidate-workspace-plan-v1`. Its command has an
absolute executable first element, `shell` is implicitly false, cwd is exactly `.`, and environment
defaults to an empty mapping rather than inheriting the host. Plans contain no local workspace path.

Materialization requires an existing physical destination parent. It creates one unique hidden
directory, copies only declared files with no-follow bounded reads and exclusive destination files,
fsyncs and re-reads them, then returns that directory. A failure removes the temporary directory.
The operation observes files one at a time; the bundle is not an atomic multi-file snapshot.

## Limits and non-goals

Bundle limits remain those of Feature 102. Runner command length, timeout and output limits are
bounded by this feature. No dependency, environment authenticity, syntax, language, or producer
identity is inferred. Runner, evaluator, receipt, archive, and recovery integration are deferred.
