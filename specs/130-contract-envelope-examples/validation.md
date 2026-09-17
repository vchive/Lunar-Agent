# Validation

## Implementation boundary

The compiler prompt now includes complete `needs_input` and `compiled` JSON objects after the
envelope rules and before the detailed contract schema. Both examples include top-level `status`
and optional evidence; their branch-specific `questions` and `contract` fields are mutually
exclusive. The compiled assignment example is internally consistent: its declared input fields,
output-scoped one-bin-per-item hard constraint, output fields and population settings all pass the
production contract dataclasses. Shape-only instructions require replacing every example fact with
the current goal and explicit answer.

The examples are immutable prompt literals and the focused test extracts their final bytes from
`RuntimeContractCompiler._prompt` with `JSONDecoder.raw_decode`. Both extracted objects pass
`_parse_response`. Removing `status` from the same compiled example still raises
`compiler response must be status=compiled with contract`. AST review confirms `_parse_response`
and `_validate_contract_shape` are unchanged from HEAD. There is no inference, repair, retry,
additional model request, transport change or persistent-state change.

## Offline verification

- **99 focused tests passed** across the new example checks plus existing contract framing,
  conversational intake and isolated compiler suites.
- **104 related contract-consumer tests passed** across automatic bundle solve, normal bundle solve,
  evolution, population defaults, role DAG CLI and objective-harness handoff.
- Feature 112's local quickstart still selects score 7 from 1/2/6/7. Terminal resume leaves
  compiler/evaluator-compiler/evaluator-auditor/Agent/candidate calls at 1/1/1/4/4 and retains one
  delivery copy.
- Ruff, compileall, `git diff --check` and Specify prerequisite/path checks pass.
- Independent review found no blocking or minor issue. It separately parsed both final prompt
  examples, verified contract dataclasses and strict contract-only rejection, and confirmed the
  parser/shape-validator ASTs are unchanged.

## Full regression

Command: `.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature130`.
The two-stage entry point completed with exit 0 and removed its temporary historical worktree.

- Current working tree: **7168 passed, 1 skipped, 24 deselected in 455.16s**. JUnit records 7169
  tests with zero failures/errors. The 24 deselected nodes are exactly the original version-bound
  Feature 123 registration tests.
- Fixed 5560eb9 checkout (product 519fea5): **24 passed in 20.44s**, zero skips/failures/errors.
  Its original 77 product, 14 measurement and 69 historical pins all verify.

## Preservation and next step

No provider, WebAgent, external evolution framework, historical campaign or captured response was
called, resumed, repaired or executed. Feature 129 remains 0/1 and all older denominators remain
unchanged. This offline result proves only that the examples are valid and strict parsing remains
closed; it does not prove model adherence, evaluator preparation or multi-file delivery.

Any fresh real check must be Feature 131 or later: independently register and push the fixed
product, task, provider and budgets before the first request, then run one new denominator without
reopening Feature 129.
