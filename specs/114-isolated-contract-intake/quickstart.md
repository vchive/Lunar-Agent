# Local verification

```sh
.venv/bin/python -m pytest -q tests/test_isolated_contract_compiler.py
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
```

The first command exercises the actual Hermes request interface with an in-memory fake model;
the second runs local subprocesses through automatic multi-file generation, evaluation, delivery
and terminal resume. Neither calls a provider. Existing `solve` syntax is unchanged.

Do not rerun Feature 113 with modified source or treat its frozen manifest verifier as a check
of this new product version. The historical result remains 0/2 on its preregistered commit.
