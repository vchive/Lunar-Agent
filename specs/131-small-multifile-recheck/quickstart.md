# Verify and run

```sh
.venv/bin/python -m pytest tests/test_measurement131_*.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python specs/131-small-multifile-recheck/measurement/campaign.py prepare
.venv/bin/python specs/131-small-multifile-recheck/measurement/campaign.py verify
```

`prepare` reads local provider configuration but makes no model request. Freeze, commit and push all
registered bytes before consuming the only slot:

```sh
.venv/bin/python specs/131-small-multifile-recheck/measurement/campaign.py run
.venv/bin/python specs/131-small-multifile-recheck/measurement/campaign.py summarize
```

The run is one native automatic multi-file solve with no campaign retry, resume, repair, fallback or
replacement. Summarization is read-only and does not call a model or execute generated code.
