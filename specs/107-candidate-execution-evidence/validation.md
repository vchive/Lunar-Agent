# Validation matrix

The three Feature 107 test files pass **107 tests**: 13 core, 91 filesystem/failure/replay,
and 3 CLI cases. Feature 106 separately passes **32 tests** after its integration fixes.

The runnable Python quickstart was executed successfully using only a temporary local shell
fixture; its recorded metadata matched read-only inspection with an exact completion pin. The
installed CLI fixture also passed for relative paths, repeat-attempt refusal and no home/Store.
Full `src`/`tests` Ruff, compileall, Specify prerequisites and `git diff --check` pass. Existing
051/074/076/078/082 frozen measurement files are unchanged relative to `027a235`.

The final full regression passed **4707 tests, 1 skipped in 232.92 seconds**. JUnit confirms
zero failures and errors. Independent review found no remaining blocking issue after the
close-failure and interruption-preservation fixes.

| Area | Required cases |
| --- | --- |
| Declaration binding | Valid and malformed/deep-mutated plan/admission; every caller pin; cross-declaration mismatch before attempt creation; returned metadata mismatch cannot create completion. |
| Durable ordering | Directory creation/fsync, canonical intent file/directory fsync, one runner call, result fsync, completion publication/fsync, final reread. No runner callback before complete intent. |
| No replay | Existing empty directory, complete attempt, partial intent, file, symlink and FIFO cause zero runner calls. A different new attempt is a distinct explicit invocation. |
| Concurrency | Two real local processes target one new attempt; only one exclusive creation authorizes a runner call. Counter remains one across repeated calls to the retained path. |
| Interruptions | Before intent completion, after intent/before runner, inside runner, after return/before result, partial result, after result/before completion and partial completion; preserve evidence and never rerun or repair through inspection. |
| Process outcomes | Success, non-zero, timeout, output limit and cleanup uncertainty; valid failed returns can have completed records. A thrown runner exception cannot be invented as a returned result. |
| Inspector | Complete exact record and intended plan/admission/pins succeeds; valid intent lacking result/completion or any temp is uncertain; malformed/extra fields, duplicates, non-finite values, noncanonical/oversized bytes, digest/size/inode mismatch fail closed. |
| Original inputs | Inspection remains independent of original source/input tree contents after recording; supplied declaration or retained attempt identity drift still fails. |
| Filesystem | Unsafe/symlinked ancestors, root overlap by identity, FIFO/hardlinks, directory replacement, same-size rewrite, replaced result, foreign and temporary nodes; never write outside held ownership or delete foreign nodes. |
| Failure retention | Open/write/fsync failure before or after runner preserves diagnostic state; no automatic cleanup after authorization, no repair and no path/OS prose leakage. |
| Redaction | Raw stdout/stderr, source/input text, local paths, commands/environment and secret-shaped output are absent from persistent/public JSON. |
| Side effects | No home/Store/evaluator/provider/Candidate/receipt/archive/event/attestation/resume or output publication. Inspection is read-only in all states. |

Real subprocess fixtures cover five `os._exit` boundaries and two-process contention, alongside
injected write/fsync/close faults. Fixtures do not prove framework effects, evaluator acceptance,
parity, external authenticity, exactly-once execution or automatic recovery.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/test_candidate_execution_evidence.py \
  tests/test_candidate_execution_evidence_files.py tests/test_candidate_execution_evidence_cli.py
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/107-candidate-execution-evidence" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
.venv/bin/python -m pytest -o addopts='' -q
git diff --check
```
