# Quickstart

Feature 104 is an offline, read-only admission boundary. The static CLI uses the same API and is
dispatched before normal config, home, or Store initialization:

```bash
lunar-agent candidate-bundle admit-execution PLAN \
  --input-root INPUT_ROOT --inputs INPUTS_JSON \
  --dependency-sha256 DEPENDENCY_SHA256 \
  --environment-sha256 ENVIRONMENT_SHA256 \
  --evaluator-kind exact-harness \
  --evaluator-sha256 EVALUATOR_SHA256 \
  --output-contract-sha256 OUTPUT_CONTRACT_SHA256 \
  --json
```

When `--input-root` is supplied, the command verifies the declared input bytes; omitting it performs
structural admission only. It prints the canonical
admission digest and bounded metadata, and does not start the plan command, import the entrypoint,
initialize Lunar home/Store, install dependencies, invoke an evaluator, or create a
Candidate/receipt/archive. Callers can also use `build_candidate_execution_admission` and
`admit_candidate_execution` from `famou`; omit `input_root` for structural-only admission, or
provide a caller-owned root for bounded no-follow byte checks.
