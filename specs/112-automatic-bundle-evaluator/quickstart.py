"""Compile and audit an evaluator, evolve source bundles, deliver and resume without a profile."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from lunar_evolution import inspect_bundle_delivery


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="lunar-auto-bundle112-")).resolve()
    (root / "inputs").mkdir()
    (root / "inputs/limit.txt").write_bytes(b"10")
    contract = {
        "schema_version": "1", "problem_id": "agent-bundle-quickstart",
        "problem_type": "continuous", "statement": "Choose the largest integer within the input limit.",
        "inputs": [{"path": "limit.txt", "format": "text", "fields": {"limit": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [{"id": "within-limit", "description": "Value lies between zero and the input limit.",
                              "source": "user_confirmed", "verification": "independent"}],
        "soft_constraints": [], "assumptions": [],
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
def main():
    root = Path(sys.argv[1]).parent
    limit = int((root / "inputs/limit.txt").read_text())
    value = json.loads((root / "output/result.json").read_text())["value"]
    valid = int(type(value) is int and 0 <= value <= limit)
    print(json.dumps({"schema_version": "1", "evaluator_id": "compiled-bundle",
        "validity": valid, "quality": float(value) if valid else None,
        "combined_score": float(value) if valid else 0.0, "detailed_scores": {},
        "error_info": [] if valid else [{"code": "within-limit", "message": "Value is outside the input limit."}]}))
if __name__ == "__main__":
    main()
'''
    python = str(Path(sys.executable).resolve())

    def probes(prefix, values):
        names = [prefix + suffix for suffix in ("low", "high", "invalid")]
        return {
            "schema_version": "1", "constraint_coverage": ["within-limit"],
            "probes": [{"name": name, "constraint_id": "within-limit" if i == 2 else None,
                        "expected_validity": 0 if i == 2 else 1,
                        "files": [{"path": "data/raw/limit.txt", "content": "10"},
                                  {"path": "output/result.json", "content": json.dumps({"value": value})}]}
                       for i, (name, value) in enumerate(zip(names, values, strict=True))],
            "score_order": [{"better": names[1], "worse": names[0]}],
        }

    envelope = {**probes("compiler-", (1, 2, 11)), "evaluator_source": harness,
                "objective": "Reject values outside [0, limit], otherwise maximize the independently read value."}
    (root / "evaluator-response.json").write_text(json.dumps(envelope))
    (root / "audit-response.json").write_text(json.dumps(probes("auditor-", (0, 9, -1))))
    worker = '''import json, sys
from pathlib import Path
prompt = sys.stdin.read()
if "contract compiler" in prompt:
    Path("compiler-calls.txt").write_text("x")
    contract = json.loads((Path(__file__).parent / "contract.json").read_text())
    print(json.dumps({"status": "compiled", "contract": contract}))
    sys.exit(0)
if "frozen local evaluator bundle" in prompt:
    Path("evaluator-compiler-calls.txt").write_text("x")
    print((Path(__file__).parent / "evaluator-response.json").read_text())
    sys.exit(0)
if "independent adversarial evaluator auditor" in prompt:
    assert "compiler-low" not in prompt
    Path("evaluator-auditor-calls.txt").write_text("x")
    print((Path(__file__).parent / "audit-response.json").read_text())
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
        "--json",
    ]
    command = [
        "solve", contract["statement"], "--evolve", "--multi-file", "--workspace", str(root / "run"),
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
                for kind in ("compiler", "evaluator-compiler", "evaluator-auditor", "agent", "candidate")}

    before = counts()
    copies = sorted(path.name for path in (parent / ".bundle-deliveries").glob(".bundle-delivery-*"))
    assert len(copies) == 1
    # No --evolve, --multi-file or --bundle-profile: recover the frozen automatic mode.
    resumed = run(["solve", "--resume", "--run-id", first["run_id"], *common])
    assert resumed["evolution"]["result"] == selected
    assert resumed["evolution"]["materialization"] == materialization
    assert copies == sorted(path.name for path in (parent / ".bundle-deliveries").glob(".bundle-delivery-*"))
    assert before == counts() == {
        "compiler": 1, "evaluator-compiler": 1, "evaluator-auditor": 1, "agent": 4, "candidate": 4,
    }
    prepared = json.loads((parent / "bundle-profile.json").read_text())
    assert prepared["evaluator"]["evaluator_id"] == "compiled-bundle"
    print(json.dumps({"root": str(root), "parent_run_id": first["run_id"],
                      "scores": scores, "best_score": selected["best_score"],
                      "delivery": str(delivery.delivery_path), "before_resume": before,
                      "after_resume": counts(), "delivery_copies": len(copies)}, indent=2))


if __name__ == "__main__":
    main()
