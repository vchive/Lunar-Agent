# Implementation Plan: Controlled Deep-Evolution Feedback Contract

## Technical approach

1. Introduce a pure `deep_feedback` module for validation, safe metric projection, candidate
   manifest hashing, and deterministic stagnation/directive derivation.
2. Extend the deep adapter's previous-round validation and prompt rendering while accepting the
   old four-field score summary as a normalized compatibility input.
3. Make `DeepEffectTrialRunner` freeze `stagnation_rounds`, derive feedback after each harness
   invocation, persist it in the round record, validate it on resume, and expose safe summaries in
   the report.
4. Add CLI configuration and SDD/README vocabulary, then exercise one- and two-run fixtures.

## Data flow

```text
fresh subject
  -> score-free receipt + candidate workspace
  -> exact private harness
  -> safe feedback projection
  -> next fresh subject request
```

The private harness remains the only score authority. The feedback module is a projection layer,
not an evaluator and not a sandbox.

## Verification strategy

- Unit-test contract bounds, legacy normalization, allowlisted metrics, manifest exclusion, and
  stagnation transitions.
- Extend deep-trial tests to assert feedback persistence, resume tamper rejection, and a genuine
  two-run/five-round aggregation.
- Run full pytest, Ruff, compileall, build, Specify prerequisites, and `git diff --check`.
