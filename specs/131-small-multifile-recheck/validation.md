# Validation

## Registration checkpoint

Product is fixed at `c730483080d5f53e5bb2d24e4bb2d2d9f45e984e`, the Feature 130 commit that
adds complete contract response envelope examples without changing the strict parser. The same task,
provider, limits, population and seed as Feature 129 are registered under a fresh `/1` denominator.

Feature 128 preparation manifest SHA-256 is
`460da2cedd52c9cf4774139df084129685c1bd686372f2662c5c683421d59a48`.
Feature 129 attempt manifest SHA-256 is
`63a056263387dbee5c9282fffb21182c9eb2fd51b6354cf871b5d4b06af10ad9`.

The six new measurement test files pass **185 tests**. Case, worker and supervision remain
byte-identical to Feature 129; analysis and observation only change private names. Registration
compares every task, runtime, capture, population, sampling, budget and outcome condition to the
fixed 129 manifest. Only campaign identity, product commit and the extra prior-attempt reference
differ. The new root is absent and no real request has started.

Full double-phase regression (`tools/run_tests.py`) passes: current **7353 passed, 1 skipped,
24 deselected in 467.95s**; frozen Feature 123 snapshot **24 passed in 14.00s**. Both JUnit reports
have zero failures/errors and overall exit is zero. Feature 112 quickstart still selects 7 from
scores 1/2/6/7, keeps calls at 1/1/1/4/4 across terminal resume, and delivers one copy.

Ruff, compileall, Specify prerequisites and whitespace checks pass. All 1748 previously tracked
product/spec/test files retain their HEAD bytes. Two independent read-only reviews found no
blocking issue. Neither review nor test made a provider request.

Manifest identity and push-before-run evidence will be recorded after preparation.

## Real result

Not started. No Feature 131 provider request has been made at this checkpoint.
