# Plan: Typed Model Failure Evidence

## Decisions and alternatives

Add a small frozen `ModelFailureEvidence` value with `reason` and `response_status`, carried by a
repository-owned `ModelRequestFailure` subtype of `RuntimeExecutionError` in `runtime.py`. The
runtime supplies evidence at boundaries it already owns; the observer accepts only exact owned
types and revalidates the fixed fields. It does not parse `str(error)`, trust an arbitrary
`evidence` attribute, or turn a response body's error label into a reason. Retain existing error
messages and cause-chain meaning where practical; the exception remains terminal and compatible
with existing `RuntimeExecutionError` catches.

Extend only the optional diagnostic format. Version 3 has the existing eleven base fields and
`model_failure={reason,response_status}`. Version 1 and budget-specific version 2 keep their
schemas and behavior. Top-level legacy `stage`, `code` and `http_status` are computed as before;
typed evidence augments that projection and never overrides it. Do not add a new top-level code
vocabulary, cause string, request counter, wall-time field, model identity or usage field.

Logging raw provider errors, headers or bodies would retain arbitrary sensitive content. Inferring
a reason from the current bounded error string would also conflate observation and prose. A
complete transport abstraction or change to parsing defaults would enlarge this feature beyond
the missing observation. Keep these alternatives out of scope.

## Classification contract

| Observed existing failure boundary | `reason` | `response_status` |
| --- | --- | --- |
| `HTTPError` or existing explicit non-2xx response rejection | `http_error` | Observed bounded integer, otherwise null |
| Direct timeout, or an exception-valued bounded `URLError.reason` chain containing a timeout | `transport_timeout` | Previously observed bounded response status, otherwise null |
| Existing transport/open/read failure without typed timeout evidence | `transport_error` | Previously observed bounded response status, otherwise null |
| Existing UTF-8 or JSON decoding failure | `invalid_json` | Observed bounded response status, otherwise null |
| Existing empty-result rejection following an unusable top-level/choices/choice/message structure | `invalid_response_shape` | Observed bounded response status, otherwise null |
| Existing empty-result rejection with a recognized content structure and no accepted text/tool calls | `empty_response` | Observed bounded response status, otherwise null |
| Existing tool-call or tool-argument parse rejection | `invalid_tool_calls` | Observed bounded response status, otherwise null |
| Existing response model-identity rejection | `invalid_model_identity` | Observed bounded response status, otherwise null |
| Existing malformed or inconsistent response usage rejection | `invalid_usage` | Observed bounded response status, otherwise null |

The reason is selected only after or at an existing rejection. Do not make `_extract_turn` more
strict. Preserve its accepted `choices[0].message`, legacy `choices[0].text`, fallback `message`
and `response` forms, content-list conversion, absent usage and tool-call defaults. Classify
structural failures with a small pure failure-only projection over the already decoded object,
or equivalent typed information from the same rejection branches. That helper returns no model
content and is not an alternate parser. Tests pin accepted and rejected forms before code changes.

Inspect at most eight exception nodes, with cycle detection, for owned typed evidence and typed
transport timeout classification. A string `URLError.reason`, exception prose or unknown type
cannot refine the reason. Invalid values never become clamped evidence. An unavailable or
out-of-range response status is null; malformed owned evidence causes a v1 fallback. A valid
version 3 payload satisfies all of these rules:

- Exact v3 fields, exact `model_failure` fields and fixed reason vocabulary; all v1 identity,
  counters, paths and size checks still apply. `stage` is `model`; no budget field is allowed.
- Top-level `code` is `model_failed`, `model_http_failed` or `timeout`. Top-level `http_status`
  remains nullable under the old rules. When it is present, it equals `response_status` and
  the reason is `http_error`; `model_http_failed` requires that observed status.
- `http_error` may retain a null top-level status for the existing explicit non-2xx branch,
  where there was no HTTPError in the old chain. A known `response_status` must be outside 200..299.
- `invalid_json`, `invalid_response_shape`, `empty_response`, `invalid_tool_calls`,
  `invalid_model_identity` and `invalid_usage` permit only null or 2xx `response_status`.
- `transport_timeout` and `transport_error` permit a null or observed bounded status because
  response reading can fail after headers arrive. They do not imply elapsed time or provider fault.

No existing historical diagnostic is upgraded. A newly written optional v3 sidecar is a bounded
subject claim, not an independently trusted account of the provider. Collection uses the existing
pre-execution request identity and cannot affect native result or recovery decisions.

## Dependency-ordered implementation and verification

1. Root reviewed this spec/plan/tasks and authorized isolated implementation before Feature 078
   launch. Its measured source excludes Feature 079. Do not commit or integrate until root review.
2. Add and observe failing tests in a new `tests/test_model_failure_evidence.py`, plus native
   integration coverage where fixture reuse makes the boundary clearer. Pin current successful
   response forms and rejection outcomes before altering parser-adjacent code.
3. Implement the owned typed evidence, existing-failure classification and v3 projection without
   changing successful runtime behavior, accounting, cause precedence or parsing defaults.
4. Run the focused matrix and native normal/deep/staged failure gates with explicit worktree
   imports, then adjacent regression tests and the appropriate repository quality gates. Record
   observed red/green results, source paths, checks and limits in tasks.
5. Obtain independent review. Root owns any commit/push, Feature 078 seal, integration and future
   registration. Never rerun a historical model, harness, candidate or failed slot for this feature.

## Test matrix

Use a loopback `ThreadingHTTPServer` on `127.0.0.1` with an ephemeral port to execute real HTTP
through `OpenAICompatibleRuntime.complete` without provider access. Cover 429/500, 200 invalid
UTF-8/JSON, JSON scalars/arrays and unusable choices/message structures, recognized empty content,
malformed tool calls/arguments, invalid model identity and malformed/inconsistent usage. Assert
both reason and observed 200/non-2xx status. Shut down and join fixtures deterministically.

Accepted-form fixtures include ordinary chat text, tool-call-only chat, legacy `choices[0].text`,
fallback `message`/`response`, mixed content lists, missing usage, missing/default tool IDs, and
invalid primary structures with an accepted existing fallback. They must retain their exact
`ModelTurn` result or existing rejection without extra requests or changed defaults.

Use controlled exceptions for otherwise platform-dependent `URLError`, direct/wrapped timeout,
read failure after an observed status, unknown exceptions, invalid status type/range and cyclic
exception chains. Include raw secret sentinels in body, URL, reason, error text and forged evidence
attributes; none may appear in diagnostic bytes. A string that says "timeout" is not timeout
evidence. Invalid owned evidence, additional keys, booleans, out-of-range numbers and forged
objects must fall back or fail strict validation without masking the original execution failure.

Run native subject adapter and `EffectTrialRunner` fixtures using the local HTTP runtime. Cover
normal failure, a deep failure after an independently scored prior round, and staged Master/Build
failure. Assert one attempt, no retry, no success receipt or new harness call after failure,
unchanged `process_nonzero_exit`, null failed usage/cost/scores, unchanged prior accepted score,
request-bound diagnostic collection and unchanged public inputs. Reuse existing hostile-file,
v1/v2 compatibility, budget-evidence and safe-publication tests.

## Runnable quickstart

These implementation checks passed from this isolated worktree; tasks records the results:

```sh
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -c 'from pathlib import Path; import famou.runtime as r; import famou.subject_diagnostics as d; assert Path(r.__file__).resolve() == Path("src/famou/runtime.py").resolve(); assert Path(d.__file__).resolve() == Path("src/famou/subject_diagnostics.py").resolve()'
PYTHONPATH="$PWD/src" /Users/liminghan/Documents/lunar_agent/.venv/bin/python -m pytest -o addopts='' -q tests/test_model_failure_evidence.py tests/test_runtime.py tests/test_subject_diagnostics.py tests/test_budget_failure_evidence.py tests/test_effect_adapters.py tests/test_effect_trial.py tests/test_deep_effect_trial.py tests/test_staged_effect_adapter.py
/Users/liminghan/Documents/lunar_agent/.venv/bin/ruff check src/famou/runtime.py src/famou/subject_diagnostics.py tests/test_model_failure_evidence.py
SPECIFY_FEATURE_DIRECTORY=specs/079-model-failure-evidence bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```

The initial draft used the read-only `--paths-only` Specify check. Root subsequently authorized
the worktree-local `.specify/feature.json` selector, and the implementation prerequisite check
updated it to Feature 079. No credentials are loaded by these commands. Full-suite tests requiring ignored historical
evidence must use root-verified pinned copies; source and frozen campaign bytes must not be
changed to satisfy environment-dependent tests.

## Constitution review, migration and complexity

No exception and no new dependency. Runtime adapter isolation remains intact; the independent
native verifier retains all result authority. The existing optional diagnostic file is the only
persistent format affected. Readers remain backward compatible with v1/v2, new readers collect
v3, and older readers may safely ignore an unfamiliar optional v3 sidecar while preserving their
original process failure. No state migration, restart, recovery action or result reinterpretation
is required. Deterministic HTTP and native failure-path tests satisfy test-first runtime coverage.
