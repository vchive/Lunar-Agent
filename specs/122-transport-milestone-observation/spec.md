# Feature 122: Local HTTP transport milestones

## Problem and outcome

Feature120's evaluator requests timed out before a final response was opened. That coarse
`open_response` observation also covers worker setup, DNS/TCP/proxy CONNECT/TLS, request
transmission, response-header waiting and redirects. Add trustworthy local milestones to future
bounded requests so a new diagnostic can distinguish these parts without changing the request.

## Acceptance

1. Preserve coarse failure phase/reason/status, request bytes, native urllib TLS/trust/ALPN,
   environment/system proxies and bypass/redirect behavior, absolute deadline, one owned worker,
   lifeline cleanup, body bounds and no application retry. Direct unbounded requests stay unchanged.
2. Optional immutable observation has exactly `last_milestone`, `http_exchange_index`, `elapsed_ms`.
   Vocabulary: worker_ready (index0, IPC/config accepted), prepare_request (new urllib HTTP exchange),
   connect (DNS/TCP/proxy tunnel/TLS), send_request (connect returned), wait_response_headers
   (request write call returned), response_headers_received (getresponse returned). Later HTTP
   redirects increment the index; proxy CONNECT belongs to connect, not another HTTP exchange.
3. Elapsed milliseconds are monotonic relative to the parent transport start. Record only complete,
   validated IPC frames; reject duplicate/unknown fields, illegal order/index/time and oversized
   frames. Legacy two/three-frame results still work. Bound detail emissions and explicitly discard
   optional observation at the limit or if its clock is invalid while continuing the original request.
4. Transport success and failure expose optional detail. Runtime failures, including response
   validation after successful HTTP, retain it independently of the unchanged coarse observation.
   Subject diagnostics use version5 only with valid typed detail and a valid v4 projection; versions
   1–4 remain readable with their exact old meaning. No persistence migration or ModelTurn change.
5. Only fixed names and bounded integers cross the observation boundary: no endpoint, host, proxy,
   headers, request/response body, credentials or exception prose. Invalid optional runtime detail
   cannot replace an original failure. Missing observation means unknown, not no request/zero usage.
6. Local fixtures demonstrate connection/TLS/proxy stalls, response-header and body stalls,
   intermediate redirect bodies and second-hop waits, exact request behavior, strict IPC and
   historical diagnostics compatibility. Existing cancellation, deadline, TLS and recovery tests pass.

## Limits

These are last observed local milestones, not provider telemetry or current-stage guarantees.
Local writes returning do not prove remote receipt, model execution or billing. A received header
may belong to an intermediate redirect; its status is not the final model response status. urllib
may redirect to a non-HTTP protocol; no later HTTP milestone is invented. DNS/TCP/tunnel/TLS remain
combined. A parent deadline can precede any detail or interrupt stdout; absent detail remains unknown.
No old campaign is rerun or relabeled; 113/115/117/120 remain separately0/2. No real model calls are
part of this increment. A small independent fixed evaluator diagnostic follows product validation.
