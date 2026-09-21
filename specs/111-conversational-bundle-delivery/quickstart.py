"""Compile a goal, evolve bundles, deliver to its parent and resume using local processes."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from lunar_evolution import CandidateEvaluationSpec, inspect_bundle_delivery


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="lunar-solve-bundle111-")).resolve()
    (root / "inputs").mkdir()
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
if "contract compiler" in prompt:
    Path("compiler-calls.txt").write_text("x")
    contract = json.loads((Path(__file__).parent / "contract.json").read_text())
    print(json.dumps({"status": "compiled", "contract": contract}))
    sys.exit(0)
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
    common = [
        "--home", str(root / "home"), "--runtime", "subprocess",
        "--command", shlex.join((python, str(root / "worker.py"))),
        "--bundle-profile", str(root / "profile.json"), "--json",
    ]
    command = [
        "solve", contract["statement"], "--evolve", "--workspace", str(root / "run"),
        "--input", str(root / "inputs/limit.txt"),
        "--population-size", "2", "--offspring-per-iteration", "2", "--islands", "1",
        "--max-rounds", "1", "--stagnation-rounds", "3", "--seed", "7", "--timeout", "3",
        *common,
    ]

    def run(args):
        completed = subprocess.run(
            [sys.executable, "-m", "lunar_evolution", *args], capture_output=True, text=True, check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        return json.loads(completed.stdout)

    first = run(command)
    (root / "first.json").write_text(json.dumps(first, indent=2))
    assert first["status"] == first["run_status"] == "succeeded", first
    selected = first["evolution"]["result"]
    materialization = first["evolution"]["materialization"]
    assert materialization["status"] == "succeeded" and materialization["mode"] == "bundle"
    assert selected["evaluated_candidates"] == selected["valid_candidates"] == 4
    parent = Path(first["workspace"])
    child = Path(first["evolution"]["workspace"])
    records = [json.loads(line) for line in (child / "evolution/archive.jsonl").read_text().splitlines()]
    scores = [item["evaluation"]["combined_score"] for item in records]
    assert scores == [1, 2, 6, 7], scores
    assert len({item["source_sha256"] for item in records}) == 1
    assert len({item["bundle_evidence"]["bundle_sha256"] for item in records}) == 4
    assert all(item["metadata"]["used_complete_parent"] for item in records[2:])
    delivery = inspect_bundle_delivery(
        parent / materialization["delivery_path"],
        expected_delivery_sha256=materialization["delivery_sha256"],
    )
    assert (delivery.delivery_path / "source/solve/helper.py").read_text().endswith("return 7\n")
    assert json.loads((delivery.delivery_path / "evaluation/report.json").read_text())["combined_score"] == 7
    assert json.loads((parent / "output/result.json").read_text())["value"] == 7
    decision = run(["deliver", first["run_id"], "--home", str(root / "home"), "--json"])
    assert decision["action"] == "deliver", decision
    assert any(path.endswith("delivery.json") for path in decision["evidence"])
    status = run(["status", first["run_id"], "--home", str(root / "home"), "--json"])
    assert status["evolution"]["linked"]["materialization"] == materialization

    def counts():
        return {kind: sum(len(p.read_bytes()) for p in (root / "run").rglob(kind + "-calls.txt"))
                for kind in ("compiler", "agent", "candidate")}

    before = counts()
    copies = sorted(path.name for path in (parent / ".bundle-deliveries").glob(".bundle-delivery-*"))
    assert len(copies) == 1
    # Intentionally omit --evolve: the stored request must preserve bundle mode.
    resumed = run(["solve", "--resume", "--run-id", first["run_id"], *common])
    assert resumed["evolution"]["result"] == selected
    assert resumed["evolution"]["materialization"] == materialization
    assert copies == sorted(path.name for path in (parent / ".bundle-deliveries").glob(".bundle-delivery-*"))
    assert before == counts() == {"compiler": 1, "agent": 4, "candidate": 4}
    print(json.dumps({"root": str(root), "parent_run_id": first["run_id"],
                      "scores": scores, "best_score": selected["best_score"],
                      "delivery": str(delivery.delivery_path), "before_resume": before,
                      "after_resume": counts(), "delivery_copies": len(copies)}, indent=2))


if __name__ == "__main__":
    main()
