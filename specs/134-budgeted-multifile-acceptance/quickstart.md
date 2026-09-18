# Offline verification and single run

```sh
.venv/bin/python -m pytest tests/test_measurement134_*.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar/test-results/feature134
.venv/bin/python specs/134-budgeted-multifile-acceptance/measurement/campaign.py prepare
.venv/bin/python specs/134-budgeted-multifile-acceptance/measurement/campaign.py verify
```

`prepare` reads local provider identity without making a request. After committing and pushing
the validated registration, ensure `HEAD == origin/main` and the campaign root is absent:

```sh
.venv/bin/python specs/134-budgeted-multifile-acceptance/measurement/campaign.py run
.venv/bin/python specs/134-budgeted-multifile-acceptance/measurement/campaign.py summarize
```

The first run consumes the only slot even if it fails. Do not retry, resume, repair responses or
replace it. Summarization reads retained evidence without executing a model or generated code,
and creates its public result/inventory once. Do not print private model response/source files.
