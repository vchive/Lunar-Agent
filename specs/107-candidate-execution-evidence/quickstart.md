# Quickstart

Use a new attempt directory for one recorded invocation of a prepared plan/admission:

```sh
lunar-agent candidate-bundle run-recorded admission.json --plan plan.json \
  --workspace ./workspace --input-root ./staged-inputs --attempt ./attempt-001 --json
lunar-agent candidate-bundle inspect-execution admission.json --plan plan.json \
  --attempt ./attempt-001 --json
```

The attempt parent must already exist. Reusing `attempt-001` always fails before another runner
invocation, including when it is empty or the previous process never started. `recorded` means
the files are complete; inspect `runner_result.status` for the independent process outcome.
Both commands accept `--admission-sha256`, `--plan-sha256`, `--bundle-sha256`, and
`--contract-sha256`. Inspection also accepts `--completion-sha256` from a prior record.

This complete local fixture exercises the public Python API and retains its temporary directory
for inspection. It does not call an evaluator, provider, model, or external framework:

```python
import hashlib
import json
import tempfile
from pathlib import Path

from famou import (
    CandidateEvaluatorPin, CandidateExecutionBudget, CandidateExecutionInput,
    CandidateSourceBundle, CandidateSourceFile, build_candidate_execution_admission,
    build_candidate_workspace_plan, inspect_candidate_execution_record,
    run_candidate_execution_recorded,
)

root = Path(tempfile.mkdtemp(prefix="lunar-recorded-example-")).resolve()
workspace, inputs = root / "workspace", root / "inputs"
workspace.mkdir()
inputs.mkdir()
source = b'printf "ok"; cat "$LUNAR_CANDIDATE_INPUT_ROOT/value"\n'
data = b"fixture"
(workspace / "run.sh").write_bytes(source)
(inputs / "value").write_bytes(data)
bundle = CandidateSourceBundle("a" * 64, "run.sh", (
    CandidateSourceFile("run.sh", len(source), hashlib.sha256(source).hexdigest()),
))
plan = build_candidate_workspace_plan(
    bundle, command=(str(Path("/bin/sh").resolve()),), contract_sha256="a" * 64,
    timeout_seconds=2, max_output_bytes=1024,
)
admission = build_candidate_execution_admission(
    plan, inputs=(CandidateExecutionInput("value", "fixture", len(data), hashlib.sha256(data).hexdigest()),),
    dependency_sha256="b" * 64, environment_sha256="c" * 64,
    evaluator=CandidateEvaluatorPin("source-only", "d" * 64),
    budget=CandidateExecutionBudget(2, 1024, 1024, 1),
)
(root / "plan.json").write_text(json.dumps(plan.to_dict()), encoding="utf-8")
(root / "admission.json").write_text(json.dumps(admission.to_dict()), encoding="utf-8")
record = run_candidate_execution_recorded(
    admission, plan=plan, workspace_path=workspace, input_path=inputs,
    attempt_path=root / "attempt-001", expected_admission_sha256=admission.digest(),
)
checked = inspect_candidate_execution_record(
    root / "attempt-001", plan=plan, admission=admission,
    expected_completion_sha256=record.completion_sha256,
)
assert checked == record
assert record.to_dict()["runner_result"]["status"] == "succeeded"
print(json.dumps(record.to_dict(), sort_keys=True))
print("Retained example directory:", root)
```

Valid incomplete evidence is `uncertain` and remains preserved. Inspection cannot repair it or
relaunch the process. A new attempt path is a new explicit execution. No Store, Candidate,
evaluator, attestation, resume, receipt, archive or scoring authority is supplied.
