# Validation

## Implementation and limits

`EvaluatorPreparationDiagnostic` is an immutable value with exactly six serialized fields:
schema_version, stage, reason, probe_index, input_index, order_index. The four local stages and
reason/index relationships are closed. Indices are strict integers (not booleans), one-based,
bounded at 64 probes/orderings and 32 inputs, or null when no position is known.

`EvaluatorPreparationError` carries a copied, validated diagnostic after normal staging cleanup.
Response admission classifies envelope/source/suite rejection as response_invalid. Native local
checks classify input format, output schema, process/report, validity, error code and score order;
snapshot additionally retains its existing undeclared-file and observed-file integrity checks.
Bundle staging integrity has no invented probe index. Candidate invocation retains its existing
file-admission semantics. Unclassified local errors use preflight_failed without guessing a cause.
The low-level candidate evaluator uses a private check signal; frozen production scoring does not
acquire a preparation diagnostic. Original exception messages remain compatible, but they and their
causes are never serialized into local_failure.

Automatic preparation writes schema 2 only when an exact typed failure carries valid detail. Its
outer stage matches local_failure.stage, category remains validation_error and recoverable=false.
Status reconstructs details only for an exact schema, valid reason/indices, coherent stage/category,
matching parent/attempt and exactly one matching started observation. Invalid detail falls back
to coarse failure. Cancellation, current evidence drift, prepared or terminal state override stale
detail. Generic exception attributes/prose cannot create detail or grant recovery. Existing runtime
failure and schema 1 paths remain unchanged. The CLI uses the existing status projection.

This is advisory error reporting; it cannot authorize freeze, scoring, delivery or continuation.
It does not diagnose provider/business root cause. process_failed deliberately groups nonzero exit,
timeout, output overflow and process launch failures; report_invalid means local report admission
failed. Response checks remain deliberately coarse. Failures outside the instrumented boundaries
(for example bundle/profile publication or loading) retain generic observations. Existing process
execution limits and capture behavior are not redesigned here.

## Focused verification

- Initial related regression: 172 passed in 8.994s.
- Automatic preparation/recovery/capability/CLI regression: 138 passed in 43.637s.
- The 112 quickstart still selects score 7 from 1/2/6/7; terminal resume retains
  contract/evaluator-compiler/auditor/Agent/candidate calls at 1/1/1/4/4 and one delivery.
- **244 new tests passed in 14.146s**, zero failures/errors/skips: 191 direct diagnostic tests and
  53 durable event/status/CLI tests. Cases include every native classification, both roles/modes
  where those checks exist, late second-input rejection before any harness, cleanup/call counts,
  valid frozen reuse and production scoring without preparation details, schema/index/field
  rejection, 33 malformed/unbound event variants, cancellation/terminal/prepared/input-drift
  precedence, runtime and generic exception impersonation, explicit continuation and terminal
  idempotence. Text CLI asserts reason and known positions and omits invalid optional detail.
- Independent implementation audit found no blocking issue. AST comparison confirms prompt,
  envelope/suite parser, snapshot request shape, frozen loader and identity definitions are intact.
  The added text CLI line consumes the already validated status projection.
- Six product/test files were frozen before the full regression. All fixtures are fresh local
  data/code; none reads or executes captured historical responses.

## Full verification

Command: `.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature127`.
The two-stage entry point completed with exit 0 and removed its temporary historical worktree.

- Current working tree: **6770 passed, 1 skipped, 24 deselected in 447.41s**. JUnit contains 6771
  tests and zero failures/errors. Only the exact original version-bound registration nodes are
  deselected; no new skips or xfails are introduced.
- Fixed 5560eb9 checkout (product 519fea5): **24 passed in 15.06s**, zero skips/failures/errors.
  These are the same deselected nodes, unchanged against their original product, with original
  77 product/14 measurement/69 history pins verified. Both phases must pass for overall success.
- All six frozen product/test files retain their hashes. Ruff across src/tests/tools, compileall,
  installed CLI help, Specify prerequisites and whitespace checks pass. All **143 local links in
  nine updated Markdown files** resolve.

## Preservation

No real provider, WebAgent, original campaign slot or captured evaluator is executed. Historical
113/115/117/120 stay separately 0/2 and 123/125 separately 0/1. All **1616 prior tracked spec/test
files** retain their initial SHA-256. Retained evidence length/hash checks match **125 16/16**,
**123 15/15** and **120 46/46** files. These are read-only checks without re-registering original
campaigns against changed product pins. The full runner separately verifies fixed pins in its
historical checkout. No prior registrations or analysis scripts were modified.

Next freeze the verified product and independently register a fresh small preparation diagnostic
before real requests, retaining compiler-once/conditional-auditor and predeclared holdout limits.
This local work does not establish real multi-file delivery, model success or causal improvement.
