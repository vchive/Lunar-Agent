# Frozen120 request analysis

The read-only analysis reconstructs the original requests using product `c569508` from local Git,
then compares request SHA-256 against retained120 journals. It does not contact the model, read
provider credentials, replay a slot, execute an evaluator, or write into old evidence directories.

```sh
.venv/bin/python -B specs/121-evaluator-prompt-protocol/diagnostics/analyze_requests.py
```

The retained [request-analysis.json](request-analysis.json) contains only sizes, counts, hashes
and safe request/result metadata. It verifies frozen registration/source and the evidence inventory
before reporting. Reproduction needs the existing local120 evidence; raw evidence is not published.

| Case | Contract request bytes | Evaluator request bytes | Minimum output probes |
| --- | ---: | ---: | ---: |
| budget_selection | 7,031 | 9,723 | 7 |
| worker_assignment | 7,619 | 11,366 | 9 |

All four request hashes match. Every request has exactly two messages (system/user), no tools,
no session history, and no duplicated contract or profile. Native requests omit temperature,
max_tokens and reasoning_effort, so provider defaults remain uncontrolled. Configured Codex
reasoning effort is not a parameter in these requests. Byte counts do not establish token counts,
context overflow or output size.

Both evaluator timeouts occurred in `open_response` with no observed HTTP status. This includes
child startup, connection and waiting for headers; it cannot distinguish provider receipt,
gateway wait, model computation, queueing or provider-internal retries. Nonstreaming requests
provided no partial progress. Timed-out output, consumption and cost remain unknown.

The121 protocol change adds explicit nested types and implementation restrictions. Using the
same retained contracts/profiles, constructed evaluator request sizes become 17,058/18,734 bytes;
these new requests were **not sent**. Added specificity grows the request and has no demonstrated
latency advantage. It fixes confirmed missing protocol instructions, not a measured timeout cause.

Remaining independent limitations: at most 62 output hard constraints can fit alongside two valid
probes; at most 32 required file paths fit in one probe. Constraints only violated by malformed or
missing schema-level output cannot necessarily be expressed by the current schema-valid negative
probe protocol. No constraint is silently dropped or reclassified by 121.
