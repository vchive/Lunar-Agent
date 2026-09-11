# Feature 081: Absolute HTTP Transport Deadline

**Status**: Completed and independently reviewed (2026-09-11).

## Problem and P1 story

Feature080 independently reproduced a successful HTTP response taking0.3100 seconds when complete
received timeout=0.15: successive socket reads can each wait within urllib's timeout while the
whole exchange exceeds it. Slow HTTP error bodies can likewise delay failure propagation. This is
a local transport defect; it does not establish the cause of the sealed078 benchmark failures.

As a caller supplying a finite request timeout, I need the HTTP exchange to stop at one absolute
deadline, with its local worker reclaimed, so a trickling or blocked response cannot keep consuming
the caller's remaining budget indefinitely.

## Acceptance criteria

1. Finite positive timeout uses an isolated standard-library HTTP worker and one parent monotonic
   deadline. Account for worker startup, request IPC, DNS, connection/TLS, redirects, response
   headers/body/error body and response IPC. Recheck the deadline before accepting a terminal
   response. Discard late or incomplete results; never automatically retry or switch transport.
2. Before returning or raising, terminate any live owned worker and reap it, closing all owned
   pipe descriptors. Blocking DNS, silent headers and trickling normal/error bodies must all be
   stoppable from a non-main caller thread. The worker inherits the caller's process group; never
   kill that shared group from the supervisor. Parent single-process death closes a dedicated
   anonymous lifeline, whose worker guardian exits the worker before it can continue HTTP work.
3. Keep timeout=None on the existing direct urllib path without spawning. Reject bool, zero,
   negative, nonfinite or unrepresentable finite timeout before worker launch/network access.
   Only finite positive exact int/float values at most86400 seconds are valid for the new bounded
   path, matching the existing subject's one-day ceiling and avoiding platform wait overflows.
4. Use sys.executable with an absolute installed helper path and isolated standard-library mode.
   No fork/preexec_fn, external command dependency or new package. Credentials, endpoint, request
   and proxy values travel only in anonymous request IPC, never argv, logs or files. Do not inherit
   the caller's full environment. Preserve ordinary environment/system proxy settings and explicit
   SSL_CERT_FILE/SSL_CERT_DIR trust settings through narrowly projected IPC configuration. Preserve
   environment NO_PROXY bypass for every redirect destination without inserting proxy credentials
   into the worker environment; system proxy mode retains native system bypass behavior.
5. Use a fixed bounded non-pickle protocol: at most a few ordered phase/status frames followed by
   one terminal result. Frame bodies may encode the existing at-most8MiB response or2000-byte HTTP
   error body. Bound request IPC to64MiB and result IPC to12MiB; reject oversized request before
   launch. Reject malformed, extra, inconsistent, unknown or oversized result frames without
   accepting a response. Arbitrary exception objects, class names or full error prose are not IPC.
6. Preserve the existing request method/body/headers, stream=False, response-byte cap, response
   parser/defaults/fallbacks and successful ModelTurn. Pure JSON/model validation stays in the
   parent. The new deadline is for HTTP transport, not preemptible parent serialization/parsing,
   OS scheduling or a hard realtime complete() return guarantee; cleanup has necessary overhead.
7. Preserve safe diagnostic categories across the process boundary using fixed projections, not
   exception pickling. Direct transport timeout maps to TimeoutError/legacy timeout;
   URLError(reason=TimeoutError(...)) without a timeout visible through the legacy __cause__ walk
   retains legacy model_failed with typed transport_timeout; HTTPError retains model_http_failed/
   status. New supervisor deadline during HTTP error-body handling preserves
   the already observed HTTP failure/status, with no raw error body required. Other supervisor
   deadline failures use transport_timeout and the last complete phase/status observation.
8. Keep version4 request timing and allv1/v2/v3 compatibility. Opening includes worker startup
   until response acquisition. Worker-reported phases are local observations; no claim about
   provider root cause. Cross-process failures reconstruct safe exceptions rather than preserving
   Python object identity; the timeout=None path retains its original exception behavior.
9. Do not alter model selection, prompts, budgets, ledger semantics, checkpoint/resume, receipts,
   effect runner or exact-harness authority. No request retry, recovered failure usage, candidate
   execution, private evaluation or real campaign. Client termination cannot guarantee that a
   server stops processing or billing an already received request; complete failed usage is null.
10. Failure-first tests use real loopback child processes and controlled local worker fixtures.
    Verify blocked DNS, headers, success/error trickle, startup/IPC delay, parent death, late
    result rejection, cleanup after exceptions, concurrency, no credentials in child argv/env,
    malformed/oversized IPC, direct None compatibility and native failed-subject no-harness rules.

## Supported boundary and limits

The worker/lifeline implementation targets the repository's POSIX macOS/Linux runtime (existing
subject diagnostics and process-group cancellation are POSIX). Tests on this host are macOS evidence,
not a Linux run. A platform lacking the required pipe/process primitives must reject finite timeout
before network dispatch rather than silently fall back to an unbounded implementation.

The isolated worker cannot inherit a caller's arbitrary installed urllib opener, monkeypatches,
custom in-memory TLS handlers or environment beyond the explicit proxy/trust projection. Document
this compatibility boundary. The fixed direct test seam is explicit; production never detects mocks
to bypass the deadline. No changes to sealed074/076/078 evidence or historical scores are permitted.
