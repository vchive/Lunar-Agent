# Feature 060: Mandatory Output Validation

## Goal

A Solver with an output-bearing algorithm contract must not deliver malformed data because a
custom acceptance rule has another successful `any` branch. Currently the controller skips a
declared OutputSpec if its rule appears anywhere in acceptance, even in an optional branch. A
CSV missing required fields can therefore be promoted and delivered as a successful result.

## Contract

- Declared outputs are an independent mandatory check, combined with the base evaluator and task
  acceptance using AND. A rule's presence inside `any`, nested alternatives, or a JSON-encoded
  acceptance string cannot suppress output validation. Generic task acceptance keeps its semantics.
- Required outputs always undergo the existing `output_valid` checks. An optional output may be
  omitted only when its path is absent under normal directories. A present file, directory,
  dangling symlink, symlink ancestor, or non-directory ancestor requires validation and cannot
  be silently treated as an omitted output.
- Use one bounded output-contract validator for ordinary/delegated Solver evaluation, execution
  of contract candidates and final evolved-output materialization. Reuse existing format, fields,
  size, encoding and confined-file checks; do not change the content formats in this feature.
- Validate up to the existing 32 OutputSpecs without counting an internal AND wrapper against
  the separate generic acceptance grammar limit. Results retain per-output `output_valid` facts
  for retry feedback without recording file contents.
- Any output failure prevents promotion and new `kind=output` ledger entries. A passing custom
  text/alternative branch or earlier candidate score cannot override the output result. Existing
  promotion, digest checks and recovery rules remain in force.
- Optional absence, valid data, no-output contracts and non-Solver tasks remain compatible.
  No schema/digest migration, score authority change or automatic re-evaluation of old runs.

## Acceptance criteria

1. Missing-field output under `any` and nested `any` makes the Solver fail, with no promoted output
   and no deliver decision; an `all` branch and valid-output success remain correct.
2. Optional absent/valid outputs pass; malformed files, directories and direct/ancestor symlinks
   fail in normal evaluation, candidate execution and evolved-output materialization.
3. Retry feedback identifies `output_valid` and a repaired second attempt can produce deliverable
   output. Base/task acceptance failures still reject otherwise valid output.
4. All 32 outputs can be checked by the independent validator, including a failure in the last
   output; it rejects unsupported or unbounded declaration inputs.
5. Regression tests fail before implementation. Focused/full tests, Ruff, compileall, build,
   Specify prerequisites and diff checks pass after implementation.

## Boundaries

Work uses local deterministic fixtures and the existing historical baseline only. No WebAgent,
private harness, model endpoint or platform query is run. Output promotion transactions, new
format rules and domain correctness scoring are outside this change. Previously accepted runs
retain their old evidence; new guarantees require a new evaluated attempt.
