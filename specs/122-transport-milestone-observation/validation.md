# Validation

## Implemented boundary

The isolated bounded HTTP worker emits a bounded stream of fixed local milestones. The parent
retains only the last validated snapshot, separately from the unchanged coarse phase and final
status. Standard-library connect/request/getresponse calls and handler TLS/context behavior remain
inherited. No request/response/endpoint text enters the new projection. There are no model calls,
retries, streaming changes, new provider parameters or campaign mutations in this feature.

Transport success exposes optional detail directly; ModelRequestFailure retains it for transport
and response-validation failures. Successful ModelTurn stays unchanged. Subject version5 is used
only with valid typed detail and valid v4 evidence; absent/invalid detail keeps the older projection.
Versions1–4 remain readable. Invalid clocks or the detail-emission cap discard optional detail while
preserving the original transport. A missing snapshot never establishes that no request was sent.

## Focused verification

151 new tests pass:53 strict IPC/observation-clock cases,15 local HTTP/TLS/proxy/redirect fixtures,
and83 runtime/subject projection cases. The combined transport/timing/failure and082/113 runtime
regression is **445 passed in 17.61s**, JUnit zero failures/errors. Normal and deep subject fixtures
persist and collect schema5 through the native path; older/direct/missing-detail cases remain v4.

Local fixtures distinguish DNS/TLS/CONNECT stalls (connect), a16MiB POST stalled during socket
writes (send_request), a fully written request with no response headers (wait_response_headers),
a302 body stall (response_headers_received/index1) and second-hop headers (wait_response_headers/
index2). Startup before worker IPC acceptance has no detailed snapshot. Original POST bytes,
authentication, redirected GET, trust/ALPN, coarse errors, deadlines and cleanup retain their tests.

An initial regression caught an observation-only clock overflow changing an existing timeout into
a generic error. The emitter now discards detail for invalid/raising clocks before its IPC write;
old timeout behavior passes. A fixture initially assumed a bound non-listening local port would
always reject immediately; this host can instead time out, so the test accepts either OS outcome
while requiring connect and no send milestone. Neither change relaxes request outcome checks.

Independent product review found no blocking issue and verified native TLS/proxy/redirect behavior,
IPC bounds and v1–v4 compatibility. Local112 quickstart again selected7 from1/2/6/7, retained
compiler/evaluator-compiler/evaluator-auditor/Agent/candidate counts1/1/1/4/4 across terminal resume,
and produced one delivery copy. Ruff, compileall, installed CLI, Specify and whitespace checks pass.

The Python3.11.15 interpreter at `/Users/liminghan/.local/bin/python3.11` also parsed all three
changed product files, imported the transport module and confirmed native HTTPS context/
check_hostname signatures and observed-class MRO. That environment has no pytest; no3.11 behavior
suite or dependency installation was performed. The fixture/full suites use the repository3.13 venv.
AST comparison confirms the parent `exchange` function (deadline/spawn/lifeline/cleanup) is unchanged.

Seven implementation/test files were frozen in `/private/tmp/lunar122-freeze.json` after focused
verification. The five121 freeze hashes,64 tracked113/115/117/120/121 files, and all46 retained120
evidence files still match their prior bytes.130 local documentation links resolved. No old verifier
was rerun to replace historical product pins.

## Final verification

Full product regression: **6200 passed, 1 skipped in 415.59s**. JUnit reports6201 tests, zero errors
and zero failures. Command: `.venv/bin/python -m pytest --junitxml=/private/tmp/lunar122-full.xml`.
All seven frozen implementation/test hashes remained unchanged through verification. Ruff,
compileall, installed CLI, Specify,130 local documentation links, whitespace and historical bytes
checks passed. Remote main was synchronized before the authorized normal commit/push.

No real-world effectiveness claim is made. Local logs use `/private/tmp/lunar122-focused.log/.xml`,
`lunar122-quickstart.log`, and `lunar122-full.log/.xml`; these are local validation logs, not portable
measurement artifacts. The product increment is complete and ready for normal commit/push.

## Next measurement boundary

Independently preregister one small synthetic typed snapshot contract (integer value bounded by an
input limit, maximize that value), compiler once and auditor only after native compiler acceptance,
at most2 requests. Keep600s/request with a separate supervisor task wall that also covers local
preflight. Use predeclared snapshot holdouts only after evaluator freeze. Commit and push exact
conditions before launch. This has its own /1 denominator and cannot establish end-to-end multi-file
delivery, real algorithm quality or a causal121 latency gain. 113/115/117/120 stay separately0/2.
