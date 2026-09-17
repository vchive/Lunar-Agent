# Verify and run

```sh
.venv/bin/python -m pytest tests/test_measurement129_*.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python specs/129-small-multifile-acceptance/measurement/campaign.py prepare
.venv/bin/python specs/129-small-multifile-acceptance/measurement/campaign.py verify
```

Prepare reads provider identity locally and makes no model requests. Freeze every registered byte
and commit/push the registration before the only real attempt:

```sh
.venv/bin/python specs/129-small-multifile-acceptance/measurement/campaign.py run
.venv/bin/python specs/129-small-multifile-acceptance/measurement/campaign.py summarize
```

One native automatic multi-file solve, no resume/retry/repair/replacement. Max20requests,600s each,
2400s total including local work,160000 observed-token stop. Verified preparation permits eight
once-only frozen evaluator holdouts with5s each; generated candidates are never replayed. Summary
does not call models, execute code or republish existing results. Report feasibility/1, optimality,
holdout agreement/8 and joint/1 separately; failure quality and unknown costs remain null.
