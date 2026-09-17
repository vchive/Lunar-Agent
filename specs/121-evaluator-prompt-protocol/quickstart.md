# Offline quickstart

```sh
.venv/bin/python -m pytest -q tests/test_evaluator_prompt_protocol.py tests/test_snapshot_evaluator_bundle.py tests/test_source_check_pipeline.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
```

Compiler and independent auditor each run once. Generated synthetic probes exercise the exact
output harness; invalid business outputs must still match the output schema. Source-aware pipeline
rejects a one-file high-scoring result; valid two-file output wins. Terminal resume creates no
additional compiler/auditor/Agent/candidate calls or delivery copies.

No real model is invoked. Frozen113/115/117/120 measurements remain unchanged; do not run their
campaign verifiers on changed product bytes. The121 read-only request diagnostic uses frozen Git
objects and existing evidence rather than replaying requests or evaluating candidate programs.
