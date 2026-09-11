# Plan: Absolute HTTP Transport Deadline

## Architecture

Base mainb6f6497. No real campaign is active; use the shared main checkout with clear file ownership.
Add a standard-library-only `http_transport.py` module that can also run as an isolated helper
script. Keep parent supervision and worker protocol colocated to avoid version drift. Runtime
integration remains small; all ModelTurn parsing stays in runtime.py. Expose a private explicit
same-process transport seam for deterministic079/080 mapping tests, never a production bypass flag.

For finite timeout, validate it, prepare bounded IPC and launch the absolute helper using
sys.executable -I -S -B, stdin/stdout pipes, stderr=DEVNULL, close_fds=True, no new session.
Project getproxies() and SSL_CERT_FILE/SSL_CERT_DIR via stdin; pass an empty/minimal safe environment
at spawn, excluding provider credentials, PYTHONPATH, SSLKEYLOGFILE and unrelated settings. A
dedicated lifeline read descriptor is the sole passed extra descriptor. Its parent write end stays
open until cleanup. The worker starts a daemon EOF guardian before making HTTP calls; the guardian
only observes parent lifetime and uses os._exit on EOF, never performs HTTP or writes evidence.

Use one absolute monotonic deadline in the supervisor. Popen.communicate(input=..., timeout=current
remaining) already multiplexes stdin/stdout on POSIX; do not add a background HTTP thread or block
on a separate stdin.write. Worker flushes fixed phase/status messages before blocking boundaries.
On timeout, use only complete valid phase frames from captured output, kill the direct PID and reap
it; never promote a terminal frame collected after expiration. Every success/failure/interrupt path
closes descriptors and reaps the worker. Cleanup cannot target the inherited PGID. A known completed
HTTP failure may retain its original status when a deadline interrupts error-body reading.

Worker checks its supplied deadline before opening a request so delayed startup cannot dispatch
after expiration. Receive at most8MiB body (the existing read cap), or2000 bytes for an HTTPError.
The IPC envelope has a small ordered phase sequence and one terminal result with fixed enum fields,
bounded status/body encodings and no arbitrary exception class/text. Parent validates shape, ordering,
base64/body lengths, terminal uniqueness and consistency. A corrupt/crashed helper is a terminal
local transport failure, not an HTTP success or retry. The trusted helper owns bounded stdout;
communicate buffers its output, so this is not an OS sandbox against a replaced malicious helper.

An explicit transport result/exception projection supplies phase/status to runtime. Preserve
direct TimeoutError versus URLError(reason=TimeoutError) legacy classification and retain HTTPError
status using safe reconstructed exceptions. In-process raw exception identity is not promised
across exec. Keep version4 phase/reason rules: deadline in open/body is transport_timeout; deadline
in read_http_error_body with a known error status is http_error. Failure timing includes supervisor
cleanup and is not a promise that elapsed_ms <= request_timeout_ms.

Typed timeout discovery follows up to eight transport nodes, including concrete URLError.reason;
legacy classification follows up to seven __cause__ nodes after its ModelRequestFailure wrapper.
Fixed opaque_timeout/cause_timeout projections preserve differences between those bounded walks
without serializing exception graphs or changing subject_diagnostics. Both successful and failed
terminal parsing recheck the deadline, and deeply nested malformed IPC is a safe protocol failure.

## Compatibility and verification

None uses the existing direct transport; no worker, environment or public runtime cancellation
interface changes. Finite calls adopt the absolute transport semantics and explicit proxy/trust
projection. Parent process_info/set_process_observer/cancel stay unchanged to avoid exposing the
shared process group as an independently cancellable child. Each request owns local process state,
so concurrent requests do not replace one another's process handle.

Validate finite timeout <=86400 seconds before launch to avoid platform poll/socket conversion
overflows. This is the same ceiling already enforced by native subjects. Project whether proxies
came from a nonempty getproxies_environment() or native system settings. In environment mode,
worker proxy_bypass must explicitly use proxy_bypass_environment(host, projected_proxies), including
every redirect host. ProxyHandler alone ignores its 'no' entry for bypass. In system mode the
worker's clean environment allows native system bypass behavior. Proxy credentials remain in IPC
and in-memory handler configuration, not worker argv/environment. Cover hit/miss/redirect behavior
using a local test proxy, with no external network traffic. After projecting trust, use the default
HTTPSHandler context so standard-library HTTP/1.1 ALPN and TLS behavior remain intact. The v4
request_timeout_ms records the caller's HTTP budget; the worker socket limit is tightened to the
remaining budget at dispatch.

Move monkeypatched finite urllib tests to a documented private direct-transport seam; they still
test079/080 exception/timing contracts. Keep actual loopback runtime/native tests on the production
child path. Add test_http_transport_deadline.py before implementation with local DNS/headers/body/
errorbody/startup/late/cleanup/parent-death and thread/concurrency fixtures. Worker fixtures may
simulate stalls but must never contact external hosts; no pickle or test-controlled production
escape hatch. Assert observed requests <=1, closed/reaped worker and unknown failed scores/usage.

Run focused tests, full main regression once, Ruff, Specify/diff, package installation/helper
availability smoke test and independent review. Verify all205/105/68 sealed078/076/074 files remain
unchanged. Root owns documentation and commit/push; implementation agent owns transport/runtime/
deadline tests and necessary079/080 test seam changes. Reviewers read only until explicitly assigned.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/test_http_transport_deadline.py tests/test_model_request_timing.py tests/test_model_failure_evidence.py tests/test_runtime.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

## Alternatives and constitution

Future/thread cancellation cannot stop running urllib/DNS. Parent signals cannot support non-main
threads and interfere with host timers. A new nonblocking HTTP/TLS stack still needs cancellable
DNS and would duplicate proxy/redirect/framing logic. An exec worker adds process overhead and
fixed IPC, but gives one reliable local lifecycle boundary without new dependencies. The existing
outer subject process-group timeout remains a separate defense. This design changes transport
behavior only and requires a new frozen registration for any later real measurement.
