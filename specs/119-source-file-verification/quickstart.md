# Offline quickstart

Run the source-check evaluation/delivery fixtures and the existing full pipeline example:

```sh
.venv/bin/python -m pytest tests/test_source_check_contract.py tests/test_candidate_source_checks.py tests/test_source_check_delivery.py tests/test_source_check_pipeline.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
```

The source-aware scenario must reject a one-file high-score candidate, accept a two-file candidate
only after output evaluation, retain source evidence in delivery, and resume without extra calls.
Exact test commands and outcomes will be retained in validation.md. Do not rerun frozen campaigns.
