# Feature Specification: Bounded Subject Failure Diagnostics

**Branch**: `main`

**Created**: 2026-09-08

**Status**: Complete

## Problem

The first real Lunar smoke completed with validity 1.0 and score 0.2079. The subsequent two
deep trials both failed before their first harness call, but only `process_nonzero_exit` remains.
One failed workspace contains a new `case/solve.py`, which violates the frozen public file set;
the actual historical exit causes cannot be recovered because stdout/stderr were discarded.
The next lower-capability-model evaluation must retain actionable, credential-safe diagnostics.

## Requirements

1. After validating the request and receipt paths, the built-in subject records a separate
   score-free failure diagnostic for runtime, post-run public projection, and receipt failures.
   The original failure must still propagate. Diagnostic write failure must not replace it.
2. Derive the sidecar from the existing success receipt path: `receipt.failure.json` in normal
   mode and `receipts/001.failure.json` in deep mode. Keep existing request/success receipt,
   run record, report and resume schemas compatible.
3. Diagnostics have a strict versioned fixed-key schema, at most 4096 bytes, bound to the
   invocation's original request SHA-256, mode, run index and optional round index. All other
   fields are bounded integers, nullable HTTP status, or fixed stage/code enumerations.
   Never persist raw exceptions, stdout/stderr, prompts, response text, tool arguments, paths,
   credentials, arbitrary metadata or scores. Unknown errors use a fixed fallback code.
4. Capture bounded model-turn/tool-step counters and distinguish model/runtime/tool/step-limit
   failures where existing events or typed exceptions provide evidence. An observed HTTP status
   may be retained as an integer without its response body. Do not guess causes from model text.
5. On failed subject invocation, the runner reads and validates the sidecar against identity
   captured before execution and copies only the normalized projection to an attempt-level
   `diagnostics/` file. Normal and deep protocols use the same collection boundary.
   Missing, malformed, oversized, stale, mismatched or unsafe diagnostics preserve the original
   `process_*` error and do not become a new failure mode.
6. Bound reads before parsing and reject unsafe paths, symlinks (including ancestors), special
   files and unsafe publication destinations. Keep raw process output discarded.
7. Diagnostics are non-authoritative subject failure claims. They do not change scoring,
   success/ready, receipts, candidate promotion, feedback, or resume decisions. They must not
   create a success receipt or permit a harness call after subject failure.
8. Both subject prompts explicitly state that the entire `case/` tree is read-only: no new
   scripts/caches or edits/deletions/renames anywhere within it. Suggest `solve.py`/`output/`
   elsewhere in the workspace and `case/data/...` for inputs. Do not relax public validation.

## Acceptance

- A model that creates `case/solve.py` then finishes is rejected without a success receipt and
  leaves a bound `public_file_set_changed` diagnostic containing none of the file contents.
- Model HTTP/runtime failure and exhaustion of model steps leave distinct safe diagnostics;
  planted credentials/private text cannot appear in serialized diagnostic bytes.
- Normal and deep second-round failures are collected correctly; the prior independently
  scored round remains intact and the failed round receives no score.
- Invalid/missing/forged/oversized/symlink/FIFO diagnostics neither authorize results nor mask
  the original process failure. Existing external subjects without sidecars remain compatible.
- Required focused/full tests, lint, compile, build, Specify checks and diff review pass.

## Scope exclusions

No WebAgent reruns, new historical score fabrication, change to private evaluator scripts,
automatic retries, new model-provider protocol, OS sandbox claim, or stored raw process logs.

The user's evaluation model change is a separate machine-local experiment configuration:
choose an actually recorded WebAgent solver model, never silently reuse the old GPT results
as same-model evidence, and preserve the old successful/failed attempts.
