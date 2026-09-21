# Operator entry and offline validation

For a retained execution whose 090 intent exists but whose 091 registration was not prepared,
first inspect the original evidence and decide whether to authorize registration. Supply your own
receipt using the exact fields in [data-model.md](data-model.md). The software does not generate
an attestation from a diagnostic report, exported bundle, raw execution file or an ordinary resume.
An attestation is a local operator statement; it does not prove that the candidate process ran.

Save the reviewed object as canonical UTF-8 JSON using:

```python
# reviewed_receipt is the complete, explicitly reviewed schema 1 object.
text = json.dumps(reviewed_receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
```

Then submit it explicitly:

```sh
lunar-evolution attest-materialization-execution PARENT CHILD \
  --receipt /absolute/path/reviewed-receipt.json --home .lunar --json
```

Success returns `status: registered`, run/task IDs and `receipt_sha256`; it registers execution
only. Ordinary resume can then validate outputs and continue delivery. A valid receipt may attest
failed execution as well as succeeded execution; registration does not claim output success.

Retry the identical receipt after interruption. A complete attested journal before SQLite
preparation requires this explicit command again. Once the prepared and attestation events exist,
ordinary resume can finish registration without the original receipt file. Missing bytes,
execution temporary files, partial/unattested journals, changed identity, reused nonce and any
088/089/092 downstream evidence are refused. Preserve those records for diagnosis.

All development verification below uses local fixtures only:

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/test_materialization_attestation_store.py \
  tests/test_materialization_attestation.py \
  tests/test_materialization_attestation_diagnostics.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
SPECIFY_FEATURE_DIRECTORY="$PWD/specs/095-manual-execution-attestation" \
  bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
git diff --check
```
