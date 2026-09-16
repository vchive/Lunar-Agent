# Quickstart

From the repository root, run the self-contained offline fixture using the installed environment:

```bash
.venv/bin/python specs/105-candidate-input-staging/quickstart.py
```

The fixture creates a plan and admission with illustrative fingerprints, invokes the installed
CLI, checks the staged binary bytes and absence of runner/home side effects, and removes its
temporary files. These example fingerprints do not authenticate an evaluator or environment.

For your own serialized Feature 104 admission and Feature 103 plan:

```bash
lunar-agent candidate-bundle stage-inputs admission.json \
  --plan plan.json \
  --input-root ./inputs \
  --staging-root ./staging \
  --admission-sha256 ADMISSION_DIGEST \
  --json
```

Both roots must already exist as disjoint physical directories. Select a staging parent outside
your candidate code workspace; the API does not receive that workspace's physical path.
Use the canonical admission
digest from `admission.digest()`, not a digest of formatted JSON bytes. To save a declaration, use
`json.dumps(admission.to_dict())` from `build_candidate_execution_admission`; the existing
`admit-execution` CLI prints summary metadata rather than a serialized declaration.

On success, `input_path` locates a new private directory containing only the declared logical
targets. Other output fields are `status`, `admission_sha256`, `plan_sha256`, `bundle_sha256`,
`contract_sha256`, `input_count`, and `total_input_bytes`. The caller owns this directory and its
cleanup. Inputs are not merged into candidate source files and no process or evaluator is started. Repeated calls
produce separate directories; this operation has no automatic reuse or recovery behavior.

The Python API exposes the same operation through `famou.stage_candidate_execution_inputs`.
Its result has an `input_path` property; `to_dict()` excludes that local path. The staged bytes
remain mutable and a future runner must recheck them when it starts execution.
