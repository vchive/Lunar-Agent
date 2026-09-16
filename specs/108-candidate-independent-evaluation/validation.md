# Validation

Feature 108 has **306 passing tests** across six files:

| File | Count | Coverage |
| --- | ---: | --- |
| `test_candidate_evaluation.py` | 25 | Real two-file candidate, independent objective/constraint check, retained snapshot, invalid outputs, no candidate rerun, pins and full reports above 16 KiB. |
| `test_candidate_evaluation_spec.py` | 164 | Detached bounded declarations, canonical identity, strict Unicode/JSON/numeric/schema/report validation, output aliases and prefix conflicts. |
| `test_candidate_evaluation_cli.py` | 18 | Installed CLI, declaration pins, bounded no-follow reads, valid/invalid exit behavior, incomplete inspection and no home/Store initialization. |
| `test_candidate_evaluation_files.py` | 68 | Original and retained inode/byte drift, unsafe nodes, root identity, optional absence, strict manifest types, partial writes, sync/readback failures and interruption retention. |
| `test_candidate_evaluation_additional.py` | 19 | Shared harness-byte validation, unused unavailable interpreter, isolated descriptor limit 128, process failure/timeout/overflow/invalid UTF-8, CSV/JSONL/text semantics. |
| `test_candidate_evaluator_process.py` | 12 | Complete raw capture through 32 KiB, stream overflow, invalid UTF-8 preservation, timeout/descendant cleanup and old runner compatibility. |

## Regression evidence

The complete repository run, after the final product-code changes, passed **4976 tests,
1 skipped in 236.854 seconds**, with zero errors/failures. Its collection included the first
269 Feature 108 tests. While that run proceeded, 37 additional tests were added (19 additional
integration cases and 18 publication failures), with no subsequent product-code changes. Those
37 also passed. Final collection is **5014 tests: 5013 passed across these runs, 1 skipped**.
The skip remains the existing case-alias test on a case-sensitive filesystem.

Evidence logs/JUnit:

- `/private/tmp/lunar108-full.log`, `/private/tmp/lunar108-full.xml`: complete baseline regression.
- `/private/tmp/lunar108-focused.xml`: original 269 Feature 108 cases, all passed.
- `/private/tmp/lunar108-additional.xml`: 19 additional cases, all passed.
- `/private/tmp/lunar108-files-final.xml`: final 68 filesystem/publication cases, all passed.

Ruff over all `src`/`tests`, compileall, Specify prerequisites, and `git diff --check` pass.
The Feature 106 runner regressions also pass with the shared raw-byte primitive. Frozen tracked
measurement material under Features 051/074/076/078/082 is unchanged relative to `027a235`.

## Runnable acceptance

The standalone quickstart was extracted verbatim and executed against the installed local
package after final product changes. The nested `solve/main.py` imports `solve/helper.py`, reads
the staged integer input and writes its result relative to the workspace root. An independent
harness checks the square and returns score **9.0**; the candidate counter stays **one** through
evaluation and read-only CLI inspection. No unused home directory is initialized.

This is a deterministic fixture score, not algorithm effectiveness or benchmark parity. No model,
provider, external producer framework, WebAgent run or new real measurement was started.

## Reviewed limits and recovery behavior

- Snapshots are observed at evaluation time. They cannot authenticate the bytes present at the
  earlier process exit; Feature 107 records are unchanged.
- The pinned harness receives copied declared inputs/outputs and a request. It must not mutate
  the snapshot or create undeclared files. No candidate source or original root paths are supplied.
- Output format failure produces a retained invalid zero-score report without harness launch.
  Failed/uncertain candidate execution, malformed reports and process failures cannot publish an
  accepted evaluation. The report can still be validly structured while its score validity is zero.
- Partial writes/interruption preserve the allocated directory. Original observations are checked
  before manifest publication. After publication, a sync/readback failure may leave a complete
  inspectable snapshot; inspection never repairs or launches anything.
- Inspection checks local consistency and optionally a saved manifest digest; it is not proof of
  external authenticity. The interpreter binary, dependency closure and same-user hostile writes
  are outside this boundary. It is not an OS sandbox or atomic multi-file snapshot.
- Candidate/receipt/archive/population/controller integration and unified recovery remain future
  work. No database migration or new attestation flow is introduced.
