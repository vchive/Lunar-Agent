"""Run a local runtime-backed bundle population, inspect delivery, then resume it."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from famou import CandidateEvaluationSpec, inspect_bundle_delivery


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="lunar-agent-bundle110-")).resolve()
    for name in ("inputs", "deliveries"):
        (root / name).mkdir()
    (root / "inputs/limit.txt").write_bytes(b"10")
    contract = {
        "schema_version": "1", "problem_id": "agent-bundle-quickstart",
        "problem_type": "continuous", "statement": "Choose the largest integer within the input limit.",
        "inputs": [{"path": "limit.txt", "format": "text", "fields": {"limit": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "assumptions": [],
        "success_criteria": ["Value lies between zero and the input limit."],
        "deliverables": ["output/result.json"],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 3},
    }
    (root / "contract.json").write_text(json.dumps(contract))
    source = '''import json, os
from pathlib import Path
from helper import choose
with Path("candidate-calls.txt").open("a") as stream:
    stream.write("x")
limit = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "limit.txt").read_text())
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": choose(limit), "claimed_score": 999999}))
'''
    (root / "template.py").write_text(source)
    harness = '''import json, sys
from pathlib import Path
# evaluator_private_marker: this source is not solver context
request = json.loads(Path(sys.argv[1]).read_text())
limit = int(Path("inputs/limit.txt").read_text())
value = json.loads(Path("output/result.json").read_text())["value"]
valid = int(type(value) is int and 0 <= value <= limit)
print(json.dumps({"schema_version": "1", "evaluator_id": "agent-bundle-quickstart",
    "validity": valid, "quality": float(value) if valid else None,
    "combined_score": float(value) if valid else 0.0, "detailed_scores": {},
    "error_info": [] if valid else [{"code": "out_of_bounds", "message": "Value exceeds the input limit."}]}))
'''
    (root / "harness.py").write_text(harness)
    python = str(Path(sys.executable).resolve())
    evaluator = CandidateEvaluationSpec(
        digest(harness.encode()), len(harness.encode()), (python, "-I"),
        evaluator_id="agent-bundle-quickstart", timeout_seconds=3,
    )
    profile = {
        "schema_version": "1", "protocol": "lunar-bundle-pipeline-v1",
        "evaluator": evaluator.to_dict(), "harness_path": "harness.py", "input_root": "inputs",
        "inputs": [{"target": "limit.txt", "source_label": "quickstart", "size": 2,
                    "sha256": digest(b"10")}],
        "command": [python], "environment": {}, "timeout_seconds": 3, "max_output_bytes": 1024,
        "dependency_sha256": digest(b"quickstart-python-standard-library-v1"),
        "environment_sha256": digest(b"quickstart-local-explicit-environment-v1"),
    }
    (root / "profile.json").write_text(json.dumps(profile))
    worker = '''import json, sys
from pathlib import Path
prompt = sys.stdin.read()
assert "LUNAR_CANDIDATE_INPUT_ROOT" in prompt
assert "evaluator_private_marker" not in prompt
context = json.loads(Path("context/context.json").read_text())
assert Path("context/inputs/limit.txt").read_bytes() == b"10"
assert not list(Path("context").rglob("harness.py"))
Path("agent-calls.txt").write_text("x")
source = (Path(__file__).parent / "template.py").read_text()
parent_path = Path("context/parent/files.json")
metadata = {"producer_score_claim": 999999}
if parent_path.exists():
    files = json.loads(parent_path.read_text())
    assert set(files) == {"solve/main.py", "solve/helper.py"}
    assert files["solve/main.py"] == source
    parent_value = int(files["solve/helper.py"].rsplit("return ", 1)[1])
    value = max(parent_value + 1, len(context["archive"]) + 4)
    metadata["used_complete_parent"] = True
else:
    value = len(context["archive"]) + 1
print(json.dumps({"entrypoint": "solve/main.py", "files": {
    "solve/main.py": source, "solve/helper.py": f"def choose(limit):\\n    return {value}\\n"},
    "metadata": metadata}))
'''
    (root / "worker.py").write_text(worker)
    command = [
        sys.executable, "-m", "famou", "evolve-bundle", str(root / "contract.json"),
        "--profile", str(root / "profile.json"), "--workspace", str(root / "run"),
        "--home", str(root / "home"), "--agent-runtime", "subprocess",
        "--agent-runtime-command", shlex.join((python, str(root / "worker.py"))),
        "--population-size", "2", "--offspring-per-iteration", "2", "--islands", "1",
        "--max-rounds", "1", "--stagnation-rounds", "3", "--seed", "7", "--timeout", "3", "--json",
    ]

    def run(extra):
        completed = subprocess.run([*command, *extra], capture_output=True, text=True, check=True)
        return json.loads(completed.stdout)

    first = run(["--destination-root", str(root / "deliveries")])
    (root / "first.json").write_text(json.dumps(first, indent=2))
    assert first["status"] == "completed" and first["run_status"] == "succeeded", first
    assert first["evaluated_candidates"] == first["valid_candidates"] == 4
    records = [json.loads(line) for line in (root / "run/evolution/archive.jsonl").read_text().splitlines()]
    scores = [item["evaluation"]["combined_score"] for item in records]
    assert scores == [1, 2, 6, 7], scores
    assert len({item["source_sha256"] for item in records}) == 1
    assert len({item["bundle_evidence"]["bundle_sha256"] for item in records}) == 4
    assert all(item["metadata"]["used_complete_parent"] for item in records[2:])
    delivery = inspect_bundle_delivery(
        first["delivery"]["delivery_path"], expected_delivery_sha256=first["delivery"]["delivery_sha256"],
    )
    assert (delivery.delivery_path / "source/solve/helper.py").read_text().endswith("return 7\n")
    assert json.loads((delivery.delivery_path / "evaluation/report.json").read_text())["combined_score"] == 7

    def counts():
        return {kind: sum(len(p.read_bytes()) for p in (root / "run").rglob(kind + "-calls.txt"))
                for kind in ("agent", "candidate")}

    before = counts()
    resumed = run(["--resume", "--run-id", first["run_id"]])
    assert resumed["best_candidate_id"] == first["best_candidate_id"]
    assert before == counts() == {"agent": 4, "candidate": 4}
    print(json.dumps({"root": str(root), "scores": scores, "best_score": first["best_score"],
                      "delivery": str(delivery.delivery_path), "before_resume": before,
                      "after_resume": counts()}, indent=2))


if __name__ == "__main__":
    main()
