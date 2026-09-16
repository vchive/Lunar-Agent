# Offline quickstart

Run the synthetic contract framing and capability tests, followed by the existing full local example:

```sh
.venv/bin/python -m pytest tests/test_contract_response_framing.py tests/test_evaluator_verification_scope.py tests/test_preparation_capability_cli.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
```

The subprocess fixture completes independent scores 1, 2, 6, 7 and a normal parent delivery.
Terminal resume must retain the original compiler/auditor/generator/candidate call counts.
New capability tests separately demonstrate a source/execution requirement stopping before the
evaluator compiler, with a retained contract and a readable preparation diagnostic.

Do not run or resume any frozen acceptance campaign as part of this quickstart.
