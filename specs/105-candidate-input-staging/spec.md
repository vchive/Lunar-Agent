# Feature 105: Candidate execution input staging

## Status

Implemented and validated offline (2026-09-16): API, static CLI, failure/interruption coverage,
installed quickstart, and full repository regression are complete.

## Problem and scope

Feature 104 declares candidate execution inputs and can verify their source bytes, but does not
provide a private location from which a future runner can consume them. Feature 105 copies only
those declared inputs into a fresh private directory without merging them into candidate source files.
It consumes a complete execution admission and its matching Feature 103 plan.

## Acceptance scenarios

1. Valid nested, binary, and empty inputs are copied under their declared logical targets into a
   new private directory. Files have mode 0600, directories 0700; unrelated files are not copied.
2. Admission, plan, bundle, contract, and optional caller pins are revalidated in memory before
   source/destination IO. Previously verified DTOs never bypass fresh input-byte checks.
3. Missing, changed, oversized, symlinked, or replaced source files are rejected. Every destination
   is re-read and compared with its declared size and SHA-256 before success.
4. Source and staging parent must be existing physical directories with no symlink ancestors and
   must not overlap, including directory identity aliases. Destinations are created exclusively.
5. Write, verification, or interruption failures clean up only the newly created, identity-matched
   tree. If cleanup cannot safely complete, a fixed cleanup error is returned; foreign replacements
   are not deleted. Existing children and source files remain untouched.
6. Repeated staging creates separate directories with the same admission identity. The returned
   metadata excludes paths and bytes; the API and CLI separately expose the local input directory.
7. The static CLI runs before config/home/Store initialization and never executes the candidate,
   imports its code, invokes an evaluator/provider, or writes receipts/archive/recovery state.

## Contract and limits

`stage_candidate_execution_inputs(admission, *, plan, input_root, staging_root,
expected_admission_sha256=None, expected_plan_sha256=None, expected_bundle_sha256=None,
expected_contract_sha256=None)` accepts a Feature 104 DTO, mapping, or bounded JSON text/bytes.
The plan is a Feature 103 DTO or mapping. The API does not implicitly open serialized declarations.
Source and staging paths are local API arguments, never part of the canonical admission digest.
The plan contains no physical source-workspace path; callers must select a staging parent outside
their code workspace when separate workspace trees are required.

The result `StagedCandidateExecutionInputs` carries an immutable admission and a local `input_path`.
Its `to_dict()` contains status, admission/plan/bundle/contract digests, input count and total bytes.
The CLI adds `input_path` explicitly so the caller can locate and clean the created directory.
Feature 104 descriptor, count, size and budget ceilings apply unchanged. Empty input sets still
require valid roots and create one empty private directory.
Source hardlinks remain valid regular files under Feature 104 checks; copies always receive new
destination inodes and never share a writable inode with the source.

Feature 104 structural errors retain `candidate_execution_*` codes. Staging filesystem failures use
fixed `candidate_input_staging_*` codes: `input_missing`, `input_unsafe`, `input_changed`,
`staging_root_unsafe`, `destination_changed`, `destination_write_failed`, `cleanup_failed`,
and `invalid`. Errors contain no local path, source content, command, or OS exception text.

## Non-goals

No runner invocation, input/source workspace merging, environment or dependency authentication,
exact evaluator, Candidate conversion, execution receipt, durable ledger, automatic reuse/resume,
or framework integration. The returned directory is caller-owned and mutable after return. The
checks observe one file at a time; they are not an atomic multi-file snapshot or an execution
authorization. A future runner must revalidate the staged bytes at its own execution boundary.
