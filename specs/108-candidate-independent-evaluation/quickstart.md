# Quickstart

Run from the repository with its installed virtual environment. This deterministic local
example executes a two-file candidate once, evaluates its result with a separate harness,
then inspects the retained evaluation. It does not use a model, producer framework or Store.

```sh
.venv/bin/python - <<'PY'
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from famou import (
    CandidateEvaluationSpec,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    CandidateSourceBundle,
    CandidateSourceFile,
    build_candidate_execution_admission,
    build_candidate_workspace_plan,
    candidate_output_contract_sha256,
    inspect_candidate_evaluation,
    run_candidate_execution_recorded,
)
from famou.algorithm import AlgorithmProblemContract

root = Path(tempfile.mkdtemp(prefix="lunar108-")).resolve()
workspace, inputs, evaluations = (root / name for name in ("workspace", "inputs", "evaluations"))
for directory in (workspace, inputs, evaluations):
    directory.mkdir()
(workspace / "solve").mkdir()
source = {
    "solve/main.py": b'''import json, os
from pathlib import Path
from helper import square
with Path("count").open("a") as marker:
    marker.write("x")
value = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "value").read_text())
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": square(value)}))
''',
    "solve/helper.py": b"def square(value):\n    return value * value\n",
}
for name, content in source.items():
    (workspace / name).write_bytes(content)
(inputs / "value").write_bytes(b"3")
contract = AlgorithmProblemContract.from_dict({
    "schema_version": "1", "problem_id": "square", "problem_type": "continuous",
    "statement": "Square the input exactly.",
    "inputs": [{"path": "value", "format": "text", "fields": {"value": "integer"}}],
    "decision_variables": ["result value"],
    "objective": {"name": "value", "direction": "maximize"},
    "hard_constraints": [], "soft_constraints": [],
    "success_criteria": ["Correct square"], "deliverables": ["output/result.json"],
    "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
})
sha = lambda content: hashlib.sha256(content).hexdigest()
bundle = CandidateSourceBundle(contract.digest(), "solve/main.py", tuple(
    CandidateSourceFile(name, len(content), sha(content)) for name, content in source.items()
))
python = str(Path(sys.executable).resolve())
plan = build_candidate_workspace_plan(
    bundle, command=(python,), contract_sha256=contract.digest(),
    timeout_seconds=2, max_output_bytes=1024,
)
harness = b'''import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
assert request["protocol"] == "lunar-candidate-evaluation-request-v1"
value = int(Path("inputs/value").read_text())
result = json.loads(Path("output/result.json").read_text())["value"]
valid = int(result == value * value)
print(json.dumps({"schema_version": "1", "evaluator_id": "exact", "validity": valid,
    "quality": None, "combined_score": float(result) if valid else 0.0,
    "detailed_scores": {}, "error_info": [] if valid else [
        {"code": "wrong", "message": "Incorrect square."}]}))
'''
harness_path = root / "harness.py"
harness_path.write_bytes(harness)
evaluator = CandidateEvaluationSpec(
    sha(harness), len(harness), (python, "-I"), timeout_seconds=2,
)
admission = build_candidate_execution_admission(
    plan, inputs=(CandidateExecutionInput("value", "fixture", 1, sha(b"3")),),
    dependency_sha256=sha(b"local-example-dependencies"),
    environment_sha256=sha(b"local-example-environment"),
    evaluator=evaluator.pin(),
    output_contract_sha256=candidate_output_contract_sha256(contract.outputs),
    budget=CandidateExecutionBudget(2, 1024, 1024, 1),
)
record = run_candidate_execution_recorded(
    admission, plan=plan, workspace_path=workspace, input_path=inputs,
    attempt_path=root / "attempt",
)
assert record.to_dict()["runner_result"]["status"] == "succeeded"
for name, value in {"admission": admission, "plan": plan,
                    "contract": contract, "evaluator": evaluator}.items():
    (root / (name + ".json")).write_text(json.dumps(value.to_dict()))
command = [
    sys.executable, "-m", "famou", "candidate-bundle", "evaluate", str(root / "admission.json"),
    "--plan", str(root / "plan.json"), "--contract", str(root / "contract.json"),
    "--evaluator", str(root / "evaluator.json"), "--harness", str(harness_path),
    "--workspace", str(workspace), "--input-root", str(inputs),
    "--attempt", str(root / "attempt"), "--evaluation-root", str(evaluations),
    "--admission-sha256", admission.digest(), "--plan-sha256", plan.digest(),
    "--bundle-sha256", bundle.digest(), "--contract-sha256", contract.digest(),
    "--completion-sha256", record.completion_sha256, "--json",
    "--home", str(root / "unused-home"),
]
completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
result = json.loads(completed.stdout)
assert result["report"]["validity"] == 1
assert result["report"]["combined_score"] == 9.0
retained = inspect_candidate_evaluation(
    result["evaluation_path"], expected_evaluation_sha256=result["evaluation_sha256"],
)
assert retained.report.combined_score == 9.0
inspection = subprocess.run([
    sys.executable, "-m", "famou", "candidate-bundle", "inspect-evaluation",
    result["evaluation_path"], "--evaluation-sha256", result["evaluation_sha256"], "--json",
], check=True, capture_output=True, text=True, timeout=15)
assert json.loads(inspection.stdout) == result
assert (workspace / "count").read_text() == "x"
assert not (root / "unused-home").exists()
print(json.dumps({"root": str(root), **result}, indent=2))
PY
```

The printed `evaluation_path` contains the input/output snapshot, harness, request, raw report
and completed manifest. `CandidateEvaluationResult.to_dict()` omits local paths; the CLI adds
`evaluation_path` so callers can inspect their result. `evaluate` exits 0 for a valid report,
1 for a retained invalid report, and 2 for an operational or validation error.
`inspect-evaluation` exits 0 for any accepted complete record, including an invalid score.

For an existing execution, use the same `candidate-bundle evaluate` arguments shown above.
The evaluator specification must have been pinned in its admission using `evaluator.pin()`;
a source-only admission cannot be repurposed by supplying a new harness at evaluation time.
Re-evaluation creates another private directory and never launches the candidate again.

The snapshot records outputs observed when evaluation starts. It does not establish that those
bytes were present at process exit. The harness is trusted local code. Its supplied bytes and
invocation are pinned, but the interpreter and dependency closure are not authenticated or
sandboxed. The example dependency/environment digests are local fixture declarations, not
verified environment identities.
