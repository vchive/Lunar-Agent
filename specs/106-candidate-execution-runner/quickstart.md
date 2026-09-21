# Quickstart

Feature 106 is an offline execution boundary for one already admitted candidate. Given the plan,
admission and private directories produced by Features 103–105, use the Python API:

```python
from lunar_evolution import run_candidate_execution

result = run_candidate_execution(
    admission,
    plan=plan,
    workspace_path=materialized_workspace,
    input_path=staged_input_path,
    expected_admission_sha256=admission.digest(),
    expected_plan_sha256=plan.digest(),
    expected_bundle_sha256=plan.bundle_sha256,
    expected_contract_sha256=plan.contract_sha256,
)
metadata = result.to_dict()
```

The equivalent installed CLI accepts serialized admission and plan files:

```bash
lunar-evolution candidate-bundle run admission.json --plan plan.json \
  --workspace ./workspace --input-root ./staged-inputs \
  --admission-sha256 "$ADMISSION_SHA256" --plan-sha256 "$PLAN_SHA256" \
  --bundle-sha256 "$BUNDLE_SHA256" --contract-sha256 "$CONTRACT_SHA256" --json
```

The runner rechecks the private workspace and staged input bytes, starts the plan's absolute
argv followed by the bundle entrypoint with `shell=False`, and supplies
`LUNAR_CANDIDATE_INPUT_ROOT` for read-only input access.
The plan command may contain up to 32 items; the runner adds the fixed entrypoint as one final
argument. The runner holds and rechecks the executable's no-follow directory/file metadata before
launch, but does not record an executable fingerprint or atomically bind that file at `exec` time.

Python callers can inspect bounded text through `result.execution.stdout` and `.stderr`.
`result.to_dict()` and the CLI omit output text and return status and bounded telemetry only. There
is no `attempt_id` parameter. Each call runs independently and does not call an evaluator, write a
receipt, create a Candidate, or initialize Store/home state.

Implementations and tests must use local deterministic fixtures; do not run OpenEvolve, WebAgent,
models, providers, remote services, or campaigns. A successful process exit is not an accepted
score and cannot be used as Lunar ranking evidence.
