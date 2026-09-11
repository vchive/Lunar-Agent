# Implementation Plan: Failed Model Request Timing

## Scope and design

Base is main0559e7c after078 seal and079 integration. No real campaign is running, so implementation
may use the main checkout with independent file ownership and review. Product changes are limited
to runtime.py and subject_diagnostics.py, plus targeted tests and these SDD documents.

Keep ModelFailureEvidence's two-field contract. Add a separate frozen ModelRequestObservation
and optional observation on ModelRequestFailure. Instrument only complete's existing transport
and response-validation path with a small request-local timer. Observe time using monotonic;
do not inject another exception layer or retain timing state across calls. An internal helper
method is acceptable if the public signature and request behavior remain unchanged.

Use a narrow guard to attach optional evidence only to the exact repository-owned failure at its
existing propagation boundary, then re-raise the same object. A clock/projection failure is ignored.
Start in open_response beforeurlopen, enter read_response_body immediately before the existing
response.read, enter validate_response for already-read response parsing/validation, and enter
read_http_error_body before the existing HTTPError body handling. Observations describe the last
entered local phase, including context-manager cleanup within that phase.

Elapsed and configured timeout are floor(seconds*1000), bounded to0..10^12. Elapsed requires two
finite, nonregressing clock readings; timeout is None or a finite positive exact int/float. A failure
to represent either discards the optional observation. Diagnostic validation accepts only exact
owned types and fixed schema. Keep the original8-node cause inspection and do not combine evidence
from different exception nodes: timing must belong to the same accepted model_failure node.

Version4 contains exactly base fields + model_failure + request_observation. Normalize v4 using
the v3 reason/status rules, then verify strict observation keys, bounds and phase compatibility:
transport_timeout/transport_error allow opening/body; response-validation reasons require
validate_response; http_error permits read_http_error_body or validate_response (the existing
explicit non2xx response branch). Unknown or invalid timing falls back tov3, preserving its valid
reason/status; absent owned reason/status keeps the legacy fallback. Reading forgedv4 fails closed.

Do not change receipt, resume or persisted controller state schemas. Old versions remain readable,
so no data migration is needed. Diagnostic publication/collection stays with the existing safe
request-bound reader/writer and size cap. Update native079 test expectations only where actual
instrumented complete now legitimately emitsv4; retain explicitv3/manual evidence coverage.

## Validation

New failure-first tests pin phases and durations using controlled clocks and real loopback requests
where feasible. They verify timeout forwarding and same exception/cause, HTTP error-body handling,
None/submillisecond inputs, malformed/nonfinite/regressing/overflow clocks, bool/foreign typed
observations, request identity,4096-byte bounds, legacy versions and secret sentinel exclusion.
Successful response tests pin request body/headers and existing accepted fallback forms. Native
normal/deep/staged tests prove failed subjects still cannot dispatch a harness or claim a score.

Run focused80/79/runtime/subject/budget/native tests, then one full main regression and Ruff,
Specify/diff checks. Independently review implementation and confirm sealed files are unchanged.
No external provider, CC Switch credential access, WebAgent run or old candidate execution is needed.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/test_model_request_timing.py tests/test_model_failure_evidence.py tests/test_runtime.py tests/test_subject_diagnostics.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

## Alternatives and constitution

Changing stream/max_tokens/retries now would change behavior without identifying the failing
boundary. Full HTTP tracing would expose unnecessary request content. A new persistent live
journal adds write/recovery contracts not needed for this bounded terminal observation.
Keep these as separate decisions. No dependencies, new state transition or authority boundary are
introduced; compatibility, bounded data and artifact-first independent verification are retained.

## Existing evidence, not causal attribution

Local readonly comparison found WebAgent's trace distinguishes request, headers and body timing;
its standard SDK transport is not vendored, so config output limits cannot establish exact wire
parameters. Lunar's request has no explicit max_tokens or reasoning parameter. Neither fact proves
the cause of078. A local HTTP fixture also demonstrated urllib's socket timeout can be exceeded by
successive body reads; the request timing feature deliberately does not change that behavior.
Root independently reproduced this using a credential-free loopback HTTP server returning a
valid JSON response in8-byte chunks separated by0.04 seconds: complete(timeout=0.15) returned
successfully after0.3100 seconds. The reviewer separately observed0.3888 seconds for a200 response
and1.3504 seconds before a503 error propagated. These are local fixture observations, not evidence
about the company platform or078's network/server behavior, and are not new benchmark scores.
