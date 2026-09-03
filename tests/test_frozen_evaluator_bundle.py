import hashlib
import json
import stat
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.cli import main
from famou.evaluator_bundle import (
    EvaluatorBundleError,
    compile_evaluator_bundle,
    load_evaluator_bundle,
)
from famou.evolution import CandidateInputArtifact
from famou.runtime import RuntimeResult
from famou.store import Store


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "frozen-routes",
            "problem_type": "routing",
            "statement": "Assign every observed order and minimize route cost.",
            "inputs": [
                {"path": "orders.csv", "format": "csv", "fields": {"id": "order ID"}}
            ],
            "decision_variables": ["route per order"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Every input order must appear exactly once.",
                    "source": "user_confirmed",
                    "verification": "independent",
                }
            ],
            "soft_constraints": [],
            "success_criteria": ["Every order is assigned."],
            "deliverables": ["route table"],
            "outputs": [
                {
                    "path": "output/routes.csv",
                    "format": "csv",
                    "fields": ["item_id", "route_id", "cost"],
                    "required": True,
                }
            ],
            "evolution": {"strategy": "loop", "max_rounds": 2, "stagnation_rounds": 3},
        }
    )


EVALUATOR_SOURCE = '''"""Frozen exact-cost evaluator."""
import csv
import json
import sys
from pathlib import Path


def report(validity, score, errors):
    return {
        "schema_version": "1",
        "evaluator_id": "frozen-exact-cost",
        "validity": validity,
        "quality": score if validity else None,
        "combined_score": score if validity else 0,
        "detailed_scores": (
            {"cost": {"value": (1 / score) - 1, "direction": "minimize"}}
            if validity else {}
        ),
        "error_info": errors,
    }


def main():
    candidate = Path(sys.argv[1])
    root = candidate.parent
    with (root / "data/raw/orders.csv").open(newline="") as stream:
        expected = [row["id"] for row in csv.DictReader(stream)]
    with (root / "output/routes.csv").open(newline="") as stream:
        routes = list(csv.DictReader(stream))
    observed = [row["item_id"] for row in routes]
    if sorted(observed) != sorted(expected) or len(observed) != len(set(observed)):
        print(json.dumps(report(0, 0, [{"code": "serve-all", "message": "coverage mismatch"}])))
        return
    cost = sum(float(row["cost"]) for row in routes)
    print(json.dumps(report(1, 1 / (1 + cost), [])))


if __name__ == "__main__":
    main()
'''


def _envelope(source: str = EVALUATOR_SOURCE) -> dict[str, object]:
    return {
        "schema_version": "1",
        "objective": (
            "Validity requires exact order coverage. For valid routes, total cost is minimized and "
            "combined_score = 1 / (1 + total_cost)."
        ),
        "evaluator_source": source,
        "constraint_coverage": ["serve-all"],
        "probes": [
            {
                "name": "valid-low-cost",
                "constraint_id": None,
                "expected_validity": 1,
                "files": [
                    {"path": "data/raw/orders.csv", "content": "id\na\n"},
                    {
                        "path": "output/routes.csv",
                        "content": "item_id,route_id,cost\na,r1,1\n",
                    },
                ],
            },
            {
                "name": "valid-high-cost",
                "constraint_id": None,
                "expected_validity": 1,
                "files": [
                    {"path": "data/raw/orders.csv", "content": "id\na\n"},
                    {
                        "path": "output/routes.csv",
                        "content": "item_id,route_id,cost\na,r1,9\n",
                    },
                ],
            },
            {
                "name": "missing-order",
                "constraint_id": "serve-all",
                "expected_validity": 0,
                "files": [
                    {"path": "data/raw/orders.csv", "content": "id\na\n"},
                    {
                        "path": "output/routes.csv",
                        "content": "item_id,route_id,cost\n",
                    },
                ],
            },
        ],
        "score_order": [{"better": "valid-low-cost", "worse": "valid-high-cost"}],
    }


class BundleRuntime:
    name = "bundle-runtime"

    def __init__(self, envelope: dict[str, object] | None = None) -> None:
        self.envelope = envelope or _envelope()
        self.bundle_calls = 0
        self.generation_calls = 0
        self.evaluator_calls = 0
        self.bundle_prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del workspace, timeout
        if "algorithm contract compiler" in prompt:
            return RuntimeResult(
                json.dumps({"status": "compiled", "contract": _contract().to_dict()})
            )
        if "frozen local evaluator bundle" in prompt:
            self.bundle_calls += 1
            self.bundle_prompts.append(prompt)
            return RuntimeResult(json.dumps(self.envelope))
        if "solver in a bounded local algorithm-evolution run" in prompt:
            self.generation_calls += 1
            cost = 9 if self.generation_calls == 1 else 1
            return RuntimeResult(
                "from pathlib import Path\n"
                "rows = Path('data/raw/orders.csv').read_text().splitlines()[1:]\n"
                "Path('output').mkdir(exist_ok=True)\n"
                f"cost = {cost}\n"
                "body = 'item_id,route_id,cost\\n' + ''.join("
                "f'{row},r1,{cost}\\n' for row in rows)\n"
                "Path('output/routes.csv').write_text(body)\n"
            )
        if "Return exactly one JSON EvaluationReport object" in prompt:
            self.evaluator_calls += 1
            raise AssertionError("ordinary model evaluator must not run")
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def _compile_bundle(
    runtime: BundleRuntime,
    root: Path,
    *,
    contract: AlgorithmProblemContract | None = None,
):
    input_path = root / "data" / "raw" / "orders.csv"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        input_path.write_text("id\nobserved-order\n", encoding="utf-8")
    content = input_path.read_bytes()
    descriptor = CandidateInputArtifact(
        "data/raw/orders.csv", len(content), hashlib.sha256(content).hexdigest()
    )
    return compile_evaluator_bundle(
        runtime,
        contract or _contract(),
        root,
        inputs=(descriptor,),
        timeout=2,
    )


def test_compiler_preflights_freezes_and_loads_bundle(tmp_path: Path) -> None:
    runtime = BundleRuntime()
    bundle = _compile_bundle(runtime, tmp_path)

    assert runtime.bundle_calls == 1
    assert len(bundle.fingerprint) == 64
    assert bundle.root == tmp_path / "evaluator-bundle"
    assert {path.name for path in bundle.root.iterdir()} == {
        "objective.md",
        "evaluator.py",
        "probes.json",
        "input-profile.json",
        "manifest.json",
    }
    assert all(path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0 for path in bundle.root.iterdir())
    assert load_evaluator_bundle(bundle.root, _contract()).fingerprint == bundle.fingerprint
    assert (bundle.root / "input-profile.json").read_bytes().endswith(b"}")
    assert not (bundle.root / "input-profile.json").read_bytes().endswith(b"\n")

    candidate = tmp_path / "candidate" / "candidate.py"
    (candidate.parent / "data" / "raw").mkdir(parents=True)
    (candidate.parent / "output").mkdir()
    candidate.write_text("pass\n", encoding="utf-8")
    (candidate.parent / "data" / "raw" / "orders.csv").write_text("id\na\n")
    (candidate.parent / "output" / "routes.csv").write_text(
        "item_id,route_id,cost\na,r1,2\n"
    )
    report = bundle(candidate, _contract())
    assert report.validity == 1
    assert report.detailed_scores["cost"]["value"] == 2


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: {**value, "constraint_coverage": []}, "coverage"),
        (
            lambda value: {
                **value,
                "evaluator_source": "import os\nprint('{}')\n",
            },
            "import",
        ),
        (
            lambda value: {
                **value,
                "evaluator_source": EVALUATOR_SOURCE.replace(
                    "1 / (1 + cost)", "1 + cost", 1
                ),
            },
            "score order",
        ),
        (
            lambda value: {
                **value,
                "probes": [
                    {**probe, "expected_validity": 1}
                    if probe["name"] == "missing-order"
                    else probe
                    for probe in value["probes"]
                ],
            },
            "constraint probe",
        ),
    ],
)
def test_bundle_preflight_fails_closed_before_promotion(
    tmp_path: Path, mutation, message: str
) -> None:
    runtime = BundleRuntime(mutation(_envelope()))
    with pytest.raises(EvaluatorBundleError, match=message):
        _compile_bundle(runtime, tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            EVALUATOR_SOURCE.replace(
                "print(json.dumps(report(1, 1 / (1 + cost), [])))",
                "print('not-json')",
            ),
            "EvaluationReport",
        ),
        (
            EVALUATOR_SOURCE.replace(
                "print(json.dumps(report(1, 1 / (1 + cost), [])))",
                "print(json.dumps({'validity': 1}))",
            ),
            "EvaluationReport",
        ),
    ],
)
def test_bundle_rejects_malformed_probe_reports(
    tmp_path: Path, source: str, message: str
) -> None:
    with pytest.raises(EvaluatorBundleError, match=message):
        _compile_bundle(BundleRuntime(_envelope(source)), tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


def test_bundle_rejects_unsafe_probe_path(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope["probes"][0]["files"][0]["path"] = "../outside.csv"
    with pytest.raises(EvaluatorBundleError, match="probe path"):
        _compile_bundle(BundleRuntime(envelope), tmp_path)
    assert not (tmp_path / "outside.csv").exists()


@pytest.mark.parametrize(
    "mode", ["tampered", "profile-tampered", "writable", "symlink", "missing"]
)
def test_frozen_bundle_loader_rejects_integrity_drift(tmp_path: Path, mode: str) -> None:
    bundle = _compile_bundle(BundleRuntime(), tmp_path)
    evaluator = bundle.root / "evaluator.py"
    if mode == "tampered":
        evaluator.chmod(0o644)
        evaluator.write_text(evaluator.read_text() + "\n# changed\n", encoding="utf-8")
        evaluator.chmod(0o444)
    elif mode == "profile-tampered":
        profile = bundle.root / "input-profile.json"
        profile.chmod(0o644)
        profile.write_text(profile.read_text() + "\n", encoding="utf-8")
        profile.chmod(0o444)
    elif mode == "writable":
        evaluator.chmod(0o644)
    elif mode == "symlink":
        bundle.root.chmod(0o755)
        objective = bundle.root / "objective.md"
        outside = tmp_path / "outside.md"
        outside.write_text(objective.read_text(), encoding="utf-8")
        objective.unlink()
        objective.symlink_to(outside)
    else:
        bundle.root.chmod(0o755)
        evaluator.unlink()

    with pytest.raises(EvaluatorBundleError):
        load_evaluator_bundle(bundle.root, _contract())


def test_frozen_bundle_loader_rejects_directory_or_contract_drift(tmp_path: Path) -> None:
    bundle = _compile_bundle(BundleRuntime(), tmp_path)
    bundle.root.chmod(0o755)
    with pytest.raises(EvaluatorBundleError, match="directory is writable"):
        load_evaluator_bundle(bundle.root, _contract())
    bundle.root.chmod(0o555)
    changed = AlgorithmProblemContract.from_dict(
        {**_contract().to_dict(), "statement": "A materially changed objective contract."}
    )
    with pytest.raises(EvaluatorBundleError, match="contract digest"):
        load_evaluator_bundle(bundle.root, changed)


def test_frozen_evaluator_cannot_modify_candidate_evidence(tmp_path: Path) -> None:
    mutating = EVALUATOR_SOURCE.replace(
        "print(json.dumps(report(1, 1 / (1 + cost), [])))",
        "(root / 'output/routes.csv').write_text('item_id,route_id,cost\\na,r1,0\\n')\n"
        "    print(json.dumps(report(1, 1 / (1 + cost), [])))",
    )
    with pytest.raises(EvaluatorBundleError, match="forbidden attribute"):
        _compile_bundle(BundleRuntime(_envelope(mutating)), tmp_path)


def test_bundle_resume_reprofiles_inputs_without_recompiling(tmp_path: Path) -> None:
    runtime = BundleRuntime()
    bundle = _compile_bundle(runtime, tmp_path)

    assert _compile_bundle(runtime, tmp_path).fingerprint == bundle.fingerprint
    assert runtime.bundle_calls == 1

    input_path = tmp_path / "data" / "raw" / "orders.csv"
    input_path.write_text("id\nchanged-order\n", encoding="utf-8")
    with pytest.raises(EvaluatorBundleError, match="input profile digest does not match"):
        _compile_bundle(runtime, tmp_path)
    assert runtime.bundle_calls == 1


def test_solve_uses_and_resumes_one_frozen_evaluator_bundle(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = BundleRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    orders = tmp_path / "orders.csv"
    orders.write_text("id\nreal-order-must-not-be-in-bundle\n", encoding="utf-8")
    home = tmp_path / "home"
    args = [
        "solve",
        "minimize route cost and write routes.csv",
        "--runtime",
        "mock",
        "--input",
        str(orders),
        "--evolve",
        "--compile-evaluator",
        "--max-rounds",
        "2",
        "--stagnation-rounds",
        "3",
        "--timeout",
        "2",
        "--json",
        "--home",
        str(home),
    ]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evolution"]["result"]["best_candidate_id"] == "candidate-0002"
    assert runtime.bundle_calls == 1
    assert runtime.evaluator_calls == 0
    bundle_root = Path(payload["workspace"]) / "evaluator-bundle"
    assert "real-order-must-not-be-in-bundle" not in "".join(
        path.read_text() for path in bundle_root.iterdir()
    )
    assert not any(
        path.name == "evaluator-bundle"
        for path in (Path(payload["evolution"]["workspace"]) / "evolution" / "agent" / "generations").rglob("*")
    )
    store = Store(home / "state.db")
    artifacts = store.list_artifacts(payload["run_id"])
    assert sum(item["kind"] == "evaluator_bundle" for item in artifacts) == 5
    assert '"row_count": 1' in runtime.bundle_prompts[0]
    assert '"name": "id"' in runtime.bundle_prompts[0]
    assert "real-order-must-not-be-in-bundle" not in runtime.bundle_prompts[0]
    manifest = json.loads((bundle_root / "manifest.json").read_text())
    assert len(manifest["input_profile_sha256"]) == 64
    assert (
        f"Private input profile SHA-256: {manifest['input_profile_sha256']}"
        in runtime.bundle_prompts[0]
    )
    request = next(
        event["payload"]
        for event in store.list_events(payload["run_id"])
        if event["type"] == "evolution_requested"
    )
    assert request["compile_evaluator"] is True

    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            payload["run_id"],
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "2",
            "--stagnation-rounds",
            "3",
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["evolution"]["run_id"] == payload["evolution"]["run_id"]
    assert runtime.bundle_calls == 1

    staged_input = Path(payload["workspace"]) / "data" / "raw" / "orders.csv"
    staged_input.write_text("id\ntampered-after-ledger\n", encoding="utf-8")
    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            payload["run_id"],
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "2",
            "--stagnation-rounds",
            "3",
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "input digest does not match" in capsys.readouterr().err
    assert runtime.bundle_calls == 1


def test_compile_evaluator_cli_rejects_conflicting_or_non_native_modes(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = BundleRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    fake = tmp_path / "evaluator"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    home = tmp_path / "home"

    assert main(
        [
            "solve",
            "routes",
            "--runtime",
            "mock",
            "--evolve",
            "--compile-evaluator",
            "--evaluator-command",
            str(fake),
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "mutually exclusive" in capsys.readouterr().err

    assert main(
        [
            "solve",
            "routes",
            "--runtime",
            "mock",
            "--evolve",
            "--strategy",
            "openevolve",
            "--compile-evaluator",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "native" in capsys.readouterr().err


def test_detached_solve_propagates_compiled_evaluator_marker(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = BundleRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    captured: dict[str, object] = {}

    class Process:
        pid = 4242

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env")
        return Process()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    monkeypatch.setattr("famou.cli.os.getpgid", lambda pid: pid)

    assert main(
        [
            "solve",
            "minimize route cost",
            "--runtime",
            "mock",
            "--evolve",
            "--compile-evaluator",
            "--detach",
            "--json",
            "--home",
            str(tmp_path / "home"),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pending"
    assert "--compile-evaluator" in captured["command"]
    assert "FAMOU_API_KEY" not in (captured["env"] or {})
