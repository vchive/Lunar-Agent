# Feature 109 quickstart

Run this block from the repository root after installing the project into `.venv`.
It creates a local temporary example, generates four two-file candidates, scores them with an
independent Python harness, delivers the selected files, and resumes the completed run.
The generator uses the complete parent source supplied in `parent_source_files`.
No model, provider, network request or external evolution framework is involved.

```sh
set -eu
LUNAR_PYTHON="$(pwd)/.venv/bin/python"
LUNAR_DEMO="$("$LUNAR_PYTHON" -c 'import tempfile; from pathlib import Path; print(Path(tempfile.mkdtemp(prefix="lunar-bundle109-")).resolve())')"
export LUNAR_DEMO

"$LUNAR_PYTHON" - <<'PY'
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

from famou.candidate_evaluation_spec import CandidateEvaluationSpec

root = Path(os.environ["LUNAR_DEMO"])
for name in ("inputs", "deliveries"):
    (root / name).mkdir()
(root / "inputs/limit.txt").write_bytes(b"10")
contract = {
    "schema_version": "1", "problem_id": "bundle-quickstart", "problem_type": "continuous",
    "statement": "Choose the largest integer between zero and the supplied limit.",
    "inputs": [{"path": "limit.txt", "format": "text", "fields": {"limit": "integer"}}],
    "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
    "hard_constraints": [], "soft_constraints": [], "assumptions": [],
    "success_criteria": ["The chosen integer is between zero and the supplied limit."],
    "deliverables": ["output/result.json"],
    "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
    "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 3},
}
(root / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
main = '''import json, os
from pathlib import Path
from helper import choose
with Path("candidate-invocations.txt").open("a") as stream:
    stream.write("x")
limit = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "limit.txt").read_text())
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": choose(limit), "claimed_score": 999999}))
'''
(root / "main-template.py").write_text(main, encoding="utf-8")
harness = '''import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
limit = int(Path("inputs/limit.txt").read_text())
value = json.loads(Path("output/result.json").read_text())["value"]
valid = int(type(value) is int and 0 <= value <= limit)
print(json.dumps({"schema_version": "1", "evaluator_id": "quickstart-exact",
    "validity": valid, "quality": float(value) if valid else None,
    "combined_score": float(value) if valid else 0.0, "detailed_scores": {},
    "error_info": [] if valid else [{"code": "out_of_bounds", "message": "Value violates the input limit."}]}))
'''
(root / "harness.py").write_text(harness, encoding="utf-8")
python = str(Path(sys.executable).resolve())
harness_bytes = harness.encode("utf-8")
evaluator = CandidateEvaluationSpec(
    hashlib.sha256(harness_bytes).hexdigest(), len(harness_bytes), (python, "-I"),
    evaluator_id="quickstart-exact", timeout_seconds=3,
)
profile = {
    "schema_version": "1", "protocol": "lunar-bundle-pipeline-v1",
    "evaluator": evaluator.to_dict(), "harness_path": "harness.py", "input_root": "inputs",
    "inputs": [{"target": "limit.txt", "source_label": "quickstart", "size": 2,
                "sha256": hashlib.sha256(b"10").hexdigest()}],
    "command": [python], "environment": {}, "timeout_seconds": 3, "max_output_bytes": 1024,
    "dependency_sha256": hashlib.sha256(b"quickstart-python-standard-library-v1").hexdigest(),
    "environment_sha256": hashlib.sha256(b"quickstart-local-python-empty-environment-v1").hexdigest(),
}
(root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
generator = '''import hashlib, json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
root = Path(__file__).parent
with (root / "generator-calls.txt").open("a") as stream:
    stream.write("x")
main = (root / "main-template.py").read_text()
metadata = {"producer_score_claim": 999999}
if request["parent"] is None:
    value = len(request["archive"]) + 1
else:
    parent_files = request["parent_source_files"]
    assert set(parent_files) == {"solver/main.py", "solver/helper.py"}
    assert parent_files["solver/main.py"] == main
    helper = parent_files["solver/helper.py"]
    parent_value = int(helper.rsplit("return ", 1)[1])
    value = max(parent_value + 1, len(request["archive"]) + 4)
    metadata["parent_helper_sha256"] = hashlib.sha256(helper.encode()).hexdigest()
print(json.dumps({"files": {"solver/main.py": main,
    "solver/helper.py": f"def choose(limit):\\n    return {value}\\n"},
    "entrypoint": "solver/main.py", "metadata": metadata}))
'''
(root / "generator.py").write_text(generator, encoding="utf-8")
(root / "generator-command.txt").write_text(
    shlex.join((python, str(root / "generator.py"))), encoding="utf-8",
)
print(f"created local demo: {root}")
PY

"$LUNAR_PYTHON" -m famou evolve-bundle "$LUNAR_DEMO/contract.json" \
  --profile "$LUNAR_DEMO/profile.json" \
  --generator-command "$(cat "$LUNAR_DEMO/generator-command.txt")" \
  --workspace "$LUNAR_DEMO/run" --home "$LUNAR_DEMO/home" \
  --max-rounds 1 --stagnation-rounds 3 --population-size 2 \
  --offspring-per-iteration 2 --islands 1 --seed 7 --timeout 3 \
  --destination-root "$LUNAR_DEMO/deliveries" --json > "$LUNAR_DEMO/first.json"

"$LUNAR_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["LUNAR_DEMO"])
result = json.loads((root / "first.json").read_text())
assert result["status"] == "completed" and result["run_status"] == "succeeded"
assert result["evaluated_candidates"] == result["valid_candidates"] == 4
assert result["best_score"] == 7
records = [json.loads(line) for line in (root / "run/evolution/archive.jsonl").read_text().splitlines()]
assert [record["evaluation"]["combined_score"] for record in records] == [1, 2, 6, 7]
assert len({record["source_sha256"] for record in records}) == 1
assert len({record["bundle_evidence"]["bundle_sha256"] for record in records}) == 4
assert all("parent_helper_sha256" in record["metadata"] for record in records[2:])
delivery = Path(result["delivery"]["delivery_path"])
assert (delivery / "source/solver/main.py").read_text() == (root / "main-template.py").read_text()
assert (delivery / "source/solver/helper.py").read_text().endswith("return 7\n")
assert json.loads((delivery / "output/result.json").read_text())["value"] == 7
assert json.loads((delivery / "evaluation/report.json").read_text())["combined_score"] == 7
counts = {
    "candidate": sum(len(path.read_bytes()) for path in (root / "run").rglob("candidate-invocations.txt")),
    "generator": len((root / "generator-calls.txt").read_bytes()),
}
assert counts == {"candidate": 4, "generator": 4}
(root / "before-counts.json").write_text(json.dumps(counts))
(root / "run-id.txt").write_text(result["run_id"])
(root / "delivery-path.txt").write_text(str(delivery))
(root / "delivery-sha256.txt").write_text(result["delivery"]["delivery_sha256"])
print(f"first run: 4 candidates; best score {result['best_score']}")
PY

"$LUNAR_PYTHON" -m famou candidate-bundle inspect-delivery \
  "$(cat "$LUNAR_DEMO/delivery-path.txt")" \
  --delivery-sha256 "$(cat "$LUNAR_DEMO/delivery-sha256.txt")" \
  --home "$LUNAR_DEMO/inspection-must-not-create-home" --json > "$LUNAR_DEMO/inspection.json"

"$LUNAR_PYTHON" -m famou evolve-bundle "$LUNAR_DEMO/contract.json" \
  --profile "$LUNAR_DEMO/profile.json" \
  --generator-command "$(cat "$LUNAR_DEMO/generator-command.txt")" \
  --workspace "$LUNAR_DEMO/run" --home "$LUNAR_DEMO/home" \
  --max-rounds 1 --stagnation-rounds 3 --population-size 2 \
  --offspring-per-iteration 2 --islands 1 --seed 7 --timeout 3 \
  --resume --run-id "$(cat "$LUNAR_DEMO/run-id.txt")" --json > "$LUNAR_DEMO/resume.json"

"$LUNAR_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["LUNAR_DEMO"])
first = json.loads((root / "first.json").read_text())
inspection = json.loads((root / "inspection.json").read_text())
resumed = json.loads((root / "resume.json").read_text())
assert inspection == first["delivery"]
assert not (root / "inspection-must-not-create-home").exists()
assert resumed["run_id"] == first["run_id"]
assert resumed["best_candidate_id"] == first["best_candidate_id"]
assert resumed["status"] == "completed" and resumed["best_score"] == 7
before = json.loads((root / "before-counts.json").read_text())
after = {
    "candidate": sum(len(path.read_bytes()) for path in (root / "run").rglob("candidate-invocations.txt")),
    "generator": len((root / "generator-calls.txt").read_bytes()),
}
assert before == after == {"candidate": 4, "generator": 4}
print("inspection: delivered; delivery digest matched")
print("resume: candidate invocations 4 -> 4; generator calls 4 -> 4")
print(f"review the selected project and outputs at: {first['delivery']['delivery_path']}")
PY
```

The helper changes while entrypoint bytes stay identical. Selection uses the harness scores
`1, 2, 6, 7`; the candidate's `claimed_score` and producer metadata do not set its score.
The delivery contains the complete source, scored output, retained evaluation report, input and
evaluator material. Output evidence records the observation at evaluation time.

Profile paths are relative to `profile.json`. Dependency and environment digests in this example
identify explicit local declarations; they do not authenticate the interpreter or installed packages.
The temporary directory remains available for inspection. This local fixture is an integration check,
not an effectiveness comparison or a new benchmark measurement.

Validated on 2026-09-16 by extracting the shell block unchanged and running it with `zsh`
from the repository root. The process exited with code `0` and printed:

```text
first run: 4 candidates; best score 7.0
inspection: delivered; delivery digest matched
resume: candidate invocations 4 -> 4; generator calls 4 -> 4
```

All embedded assertions passed, including complete parent source context, four distinct bundle
identities with identical entrypoint digests, complete selected delivery, and no inspection home.
