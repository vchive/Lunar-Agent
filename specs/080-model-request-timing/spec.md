# Feature 080: Failed Model Request Timing

**Status**: Complete; independently reviewed and verified on main.

## Problem and user story

Feature078 accepted both Master plans and entered Build, but both subjects failed at approximately
5280 seconds with model/timeout and no complete output or score. Its frozen v1 evidence does not
identify when the last request started or whether transport opening, response body reading or
validation was active. Feature079 adds a fixed reason/status, but still lacks request-local timing.

As the operator of a future invocation, I need the failed request's local phase, elapsed time and
actual timeout argument, so I can select a subsequent transport or delivery change using evidence.
This feature does not claim to repair078, recover its missing measurements or improve validity.

## Acceptance criteria

1. Add an immutable repository-owned `ModelRequestObservation` carrying only `phase`, `elapsed_ms`
   and `request_timeout_ms`. Attach it to the same existing owned `ModelRequestFailure`; preserve
   its original cause, message, failure reason/status and propagation depth.
2. Phases are exactly `open_response`, `read_response_body`, `validate_response` and
   `read_http_error_body`. Opening includes DNS/connect/TLS/request send and `urlopen` response
   acquisition; it does not identify any of those substeps. The error-body phase means error-body
   handling was entered, not that body reading caused the failure.
3. Start monotonic observation immediately before the transport call and stop at the original
   typed error propagation boundary. Successful responses have unchanged ModelTurn values and
   parsing behavior. Do not log successful timings or create a per-request history file.
4. Quantize both durations by flooring seconds to milliseconds. Fields are non-boolean integers
   in0..10^12. A positive submillisecond timeout becomes0; `request_timeout_ms=null` means no
   explicit timeout. Invalid/unrepresentable timeout or clock readings, regressing/nonfinite clocks,
   failed observation construction or invalid/foreign typed observations discard the entire
   observation. The original valid v3 reason/status must still survive.
5. Add strict diagnostic version4 with the existing base fields plus unchanged `model_failure`
   and exactly one `request_observation` object. Version4 accepts only the existing model-failure
   classification rules and phase/reason consistency. Versions1/2/3 remain accepted unchanged;
   manually raised typed failures lacking timing still emitv3, unknown exceptions keepv1.
6. All diagnostic data stays within the existing4096-byte cap and request/mode/run/round binding.
   No endpoint, headers, bodies, raw exception text, tool arguments, model output, credentials,
   candidate paths, token estimates, scores or arbitrary metadata may enter the added fields.
   Observation failure never masks the original failure or authorizes a retry.
7. Preserve outgoing body/headers, `stream=False`, timeout argument, network call/read count,
   error-body handling, response acceptance/defaults, ledger, prompts, stage boundaries, receipts,
   and exact-harness authority. No new retry, provider probe, cancellation, model call or scoring.
8. Verify failure first with controlled clocks, actual loopback HTTP and deterministic transport
   fixtures. Cover opening/body/validation/error-body boundaries, legacy versions, hostile typed
   evidence, normal/deep/staged authority, unchanged success, no secrets and no additional calls.

## Limits

This is terminal failure evidence only. It cannot observe an outstanding request killed by an outer
process, distinguish server work from network waiting, report complete failed usage, or supply an
independent Master/Build duration. The timeout is the value passed to urllib, not a guaranteed
whole-request deadline: socket reads and error-body handling can outlast it cumulatively. Any fix
to that behavior requires a separate behavioral specification and is not mixed into this feature.
Sealed074/076/078 files and all historical results remain unchanged. No campaign is launched here.
