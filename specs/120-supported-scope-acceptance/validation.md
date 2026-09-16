# Validation

## Before launch (2026-09-17)

Product pinned to `c5695088c83bf69188bd7ae222056c8b63233656`; product119 previously passed
5912 tests and one skip. This feature changes only measurement and documentation.

- 86 new measurement tests plus two existing source-aware pipeline fixtures: 88 passed.
- Combined113/115/117/120 measurement regressions plus source pipeline: **304 passed**,
  JUnit zero failures/errors, 8.222 seconds. Command:
  `.venv/bin/python -m pytest -q tests/test_measurement113_*.py tests/test_measurement115_*.py tests/test_measurement117_*.py tests/test_measurement120_*.py tests/test_source_check_pipeline.py`.
- New cases cover scope/registration drift, source contract omission/threshold changes, source
  evidence/delivery downgrade or removal, independent output disagreement, once-only routing,
  unknown cleanup, fixed denominator, unknown consumption and summary-before-finish/repeat rejection.
- Existing112 quickstart delivered score7 from1/2/6/7. Resume retained compiler/evaluator-compiler/
  evaluator-auditor/Agent/candidate counts1/1/1/4/4 and one delivery copy.
- Ruff, compileall, Specify prerequisites and diff whitespace checks passed.
- Safe provider metadata matches117; requested model remains GLM-5.2. No model call in preparation.
- New manifest SHA256: `d8dd67c250161aed751ebf85ae10f330b03c8eedfaeb7356011e4e4ff7f7270e`.
  `campaign.py verify` passed. Registration must be committed and pushed before launch.

Logs: `/private/tmp/lunar120-focused.log`, `/private/tmp/lunar120-focused.xml`,
`/private/tmp/lunar120-new.log`, `/private/tmp/lunar120-new.xml`,
`/private/tmp/lunar120-quickstart.log`. These local paths are not portable product evidence.

## After launch

Registration was pushed as `f3b575c5bf86019b27529339c88f6f936a779654` before either slot.
Both slots ran once: primary/envelope 0/2, contract compilation succeeded, evaluator requests
returned transport timeouts at 600.004/600.003 seconds. No evaluator, candidate, delivery or
holdout execution; quality/gap null. Four requests have a known 16,161-token subtotal and two
unknown-consumption timeouts. Workers exited 1; supervisor completed successfully; cleanup passed.

Read-only evidence audit matched all 46 retained files (size/SHA), 77 product pins, 19 measurement
pins and 46 historical pins. Two complete private response bodies are 3,817/6,626 bytes and match
retained SHA256 metadata. No response text was published. Measured results, diagnostics and
file inventory are retained in [postrun report](postrun/report.md); original registration unchanged.
