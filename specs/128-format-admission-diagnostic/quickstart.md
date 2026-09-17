# Verify and run

```sh
.venv/bin/python -m pytest tests/test_measurement128_*.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
.venv/bin/python specs/128-format-admission-diagnostic/measurement/campaign.py prepare
.venv/bin/python specs/128-format-admission-diagnostic/measurement/campaign.py verify
```

Prepare only reads configured provider identity locally. Review and push all registered bytes
before real requests. Then execute the sole slot and publish retained results once:

```sh
.venv/bin/python specs/128-format-admission-diagnostic/measurement/campaign.py run
.venv/bin/python specs/128-format-admission-diagnostic/measurement/campaign.py summarize
```

At most2isolated requests,600s each,1320s total including local checks and eight conditional
post-freeze holdouts (5s each). No retry/resume/repair/fallback/replacement. A started slot is
consumed even when failed. Summary is read-only over retained evidence and publishes once;
original slots/private captured responses/evaluators are never replayed. Optional local_failure
is a fixed native stage/reason/index observation, not an authority or a business root-cause claim.
