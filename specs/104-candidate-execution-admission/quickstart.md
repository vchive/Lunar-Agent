# Quickstart

The Feature 104 core API is implemented as an offline, read-only admission boundary. The static
CLI is being wired to the same API and will be dispatched before normal config, home, or Store
initialization. Its intended interface is:

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

The command verifies only the declared input bytes and structural pins. It prints the canonical
admission digest and bounded metadata, and does not start the plan command, import the entrypoint,
initialize Lunar home/Store, install dependencies, invoke an evaluator, or create a
Candidate/receipt/archive. Until the CLI wiring lands, callers can use
`build_candidate_execution_admission` and `admit_candidate_execution` from `famou`; omit
`input_root` for structural-only admission, or provide a caller-owned root for bounded no-follow
byte checks.
