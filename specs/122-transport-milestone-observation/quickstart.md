# Quickstart

From the repository root, with the development environment installed:

```sh
.venv/bin/python -m pytest tests/test_http_transport_milestones.py tests/test_transport_observation_diagnostics.py tests/test_http_transport_observation_ipc.py
.venv/bin/python -m pytest tests/test_http_transport_deadline.py tests/test_http_transport_tls.py tests/test_model_request_timing.py tests/test_model_failure_evidence.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
```

All HTTP fixtures bind loopback and use synthetic data; no provider credentials or real requests.
Inspect optional TransportFailure.observation: a local server that accepts the full request then
withholds headers ends at wait_response_headers/index1, while a302 intermediate body stall ends
at response_headers_received/index1 with coarse open_response and no final status. These local
facts do not identify model computation or remote queuing. Old diagnostic versions stay readable.

| Last milestone | What was observed locally |
| --- | --- |
| No detail | No valid complete snapshot was retained; request activity and usage are unknown. |
| worker_ready, index0 | Worker accepted and validated request IPC/config; parent startup is included in elapsed time. |
| prepare_request | urllib began this HTTP exchange; later HTTP redirect exchanges increment the index. |
| connect | Entered native connection establishment, including DNS/TCP/proxy CONNECT/TLS. |
| send_request | Native connection call returned; the request-write call has not yet been observed returning. |
| wait_response_headers | Native request-write call returned; no response-header return has yet been observed for this exchange. |
| response_headers_received | Native getresponse returned, possibly for an intermediate redirect. Coarse phase/final status remain separate. |

The names describe the last observation, not a guarantee of the worker's current activity. A
nonzero worker exit may discard its progress. Observation limits or an unusable clock drop detail;
they do not change the request or turn unknown consumption into zero. Successful runtime ModelTurn
retains its existing fields; direct callers of exchange can inspect successful transport detail.
