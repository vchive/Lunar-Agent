# Quickstart (draft)

Feature 104 is not implemented yet. The intended static command is:

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

The command will verify only the declared input bytes and structural pins. It will print the
canonical admission digest and bounded metadata, and will not start the plan command, import the
entrypoint, initialize Lunar home/Store, install dependencies, invoke an evaluator, or create a
Candidate/receipt/archive.
