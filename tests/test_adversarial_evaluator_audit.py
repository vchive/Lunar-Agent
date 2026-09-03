import copy
import hashlib
import json
import stat
from pathlib import Path

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.algorithm import AlgorithmProblemContract
from famou.cli import main
from famou.evaluator_bundle import (
    EvaluatorBundleError,
    compile_evaluator_bundle,
    load_evaluator_bundle,
)
from famou.evolution import CandidateInputArtifact
from famou.runtime import ModelTurn, RuntimeResult
from famou.transcript import SessionTranscript


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "audited-routes",
            "problem_type": "routing",
            "statement": "Assign every order exactly once and minimize cost.",
            "inputs": [
                {"path": "orders.csv", "format": "csv", "fields": {"id": "order ID"}}
            ],
            "decision_variables": ["route per order"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Every input order appears exactly once.",
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
        }
    )


EXACT_EVALUATOR = '''"""AUDIT_SOURCE_MARKER exact coverage and cost."""
import csv
import json
import sys
from pathlib import Path


def result(validity, score, code=None):
    return {
        "schema_version": "1",
        "evaluator_id": "audited-exact-cost",
        "validity": validity,
        "quality": score if validity else None,
        "combined_score": score if validity else 0,
        "detailed_scores": {"cost": {"value": (1 / score) - 1, "direction": "minimize"}} if validity else {},
        "error_info": [] if code is None else [{"code": code, "message": "coverage mismatch"}],
    }


def main():
    root = Path(sys.argv[1]).parent
    with (root / "data/raw/orders.csv").open(newline="") as stream:
        expected = [row["id"] for row in csv.DictReader(stream)]
    with (root / "output/routes.csv").open(newline="") as stream:
        routes = list(csv.DictReader(stream))
    observed = [row["item_id"] for row in routes]
    if sorted(observed) != sorted(expected) or len(observed) != len(set(observed)):
        print(json.dumps(result(0, 0, "serve-all")))
        return
    cost = sum(float(row["cost"]) for row in routes)
    print(json.dumps(result(1, 1 / (1 + cost))))


if __name__ == "__main__":
    main()
'''


WEAK_EVALUATOR = EXACT_EVALUATOR.replace(
    "if sorted(observed) != sorted(expected) or len(observed) != len(set(observed)):",
    "if len(observed) != len(expected):",
).replace("exact coverage and cost", "weak row-count coverage")


def _probe(name: str, validity: int, orders: str, routes: str) -> dict[str, object]:
    return {
        "name": name,
        "constraint_id": "serve-all" if validity == 0 else None,
        "expected_validity": validity,
        "files": [
            {"path": "data/raw/orders.csv", "content": orders},
            {"path": "output/routes.csv", "content": routes},
        ],
    }


def _self_suite() -> dict[str, object]:
    marker = "compiler-self-probe-marker"
    return {
        "schema_version": "1",
        "constraint_coverage": ["serve-all"],
        "probes": [
            _probe(
                marker + "-better",
                1,
                "id\na\nb\n",
                "item_id,route_id,cost\na,r1,1\nb,r1,1\n",
            ),
            _probe(
                marker + "-worse",
                1,
                "id\na\nb\n",
                "item_id,route_id,cost\na,r1,9\nb,r1,9\n",
            ),
            _probe(
                marker + "-missing",
                0,
                "id\na\nb\n",
                "item_id,route_id,cost\na,r1,1\n",
            ),
        ],
        "score_order": [
            {
                "better": marker + "-better",
                "worse": marker + "-worse",
            }
        ],
    }


def _audit_suite() -> dict[str, object]:
    return {
        "schema_version": "1",
        "constraint_coverage": ["serve-all"],
        "probes": [
            _probe(
                "audit-better",
                1,
                "id\nx\ny\n",
                "item_id,route_id,cost\nx,r1,2\ny,r1,2\n",
            ),
            _probe(
                "audit-worse",
                1,
                "id\nx\ny\n",
                "item_id,route_id,cost\nx,r1,7\ny,r1,7\n",
            ),
            _probe(
                "audit-duplicate-id",
                0,
                "id\nx\ny\n",
                "item_id,route_id,cost\nx,r1,2\nx,r1,2\n",
            ),
        ],
        "score_order": [{"better": "audit-better", "worse": "audit-worse"}],
    }


def _compiler_envelope(source: str = EXACT_EVALUATOR) -> dict[str, object]:
    return {
        "schema_version": "1",
        "objective": "Exact coverage is required; lower total route cost is better.",
        "evaluator_source": source,
        **{key: value for key, value in _self_suite().items() if key != "schema_version"},
    }


class AuditRuntime:
    name = "audit-runtime"

    def __init__(
        self,
        *,
        source: str = EXACT_EVALUATOR,
        audit: object | None = None,
    ) -> None:
        self.envelope = _compiler_envelope(source)
        self.audit = _audit_suite() if audit is None else audit
        self.compiler_calls = 0
        self.audit_calls = 0
        self.generation_calls = 0
        self.prompts: list[tuple[str, str]] = []
        self.workspaces: list[tuple[str, Path]] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        if "algorithm contract compiler" in prompt:
            return RuntimeResult(
                json.dumps({"status": "compiled", "contract": _contract().to_dict()})
            )
        if "frozen local evaluator bundle" in prompt:
            self.compiler_calls += 1
            self.prompts.append(("compiler", prompt))
            self.workspaces.append(("compiler", workspace))
            return RuntimeResult(json.dumps(self.envelope))
        if "adversarial evaluator auditor" in prompt:
            self.audit_calls += 1
            self.prompts.append(("auditor", prompt))
            self.workspaces.append(("auditor", workspace))
            if isinstance(self.audit, str):
                return RuntimeResult(self.audit)
            return RuntimeResult(json.dumps(self.audit))
        if "solver in a bounded local algorithm-evolution run" in prompt:
            self.generation_calls += 1
            raise AssertionError("solver must not run before evaluator audit succeeds")
        raise AssertionError(f"unexpected runtime prompt: {prompt[:80]}")


class IsolatedAuditModel:
    name = "isolated-audit-model"
    api_key = None

    def __init__(self) -> None:
        self.requests: list[
            tuple[list[dict[str, object]], tuple[dict[str, object], ...]]
        ] = []

    def complete(self, messages, tools=(), timeout=None):
        del timeout
        self.requests.append((messages, tools))
        prompt = str(messages[-1].get("content", ""))
        if "frozen local evaluator bundle" in prompt:
            return ModelTurn(json.dumps(_compiler_envelope()))
        if "adversarial evaluator auditor" in prompt:
            return ModelTurn(json.dumps(_audit_suite()))
        raise AssertionError(f"unexpected model prompt: {prompt[:80]}")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def _compile(runtime: AuditRuntime, root: Path):
    source = root / "data" / "raw" / "orders.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("id\nprivate-real-order\n", encoding="utf-8")
    content = source.read_bytes()
    descriptor = CandidateInputArtifact(
        "data/raw/orders.csv", len(content), hashlib.sha256(content).hexdigest()
    )
    return compile_evaluator_bundle(
        runtime, _contract(), root, inputs=(descriptor,), timeout=2
    )


def test_compilation_runs_one_isolated_audit_and_freezes_evidence(tmp_path: Path) -> None:
    runtime = AuditRuntime()
    bundle = _compile(runtime, tmp_path)

    assert runtime.compiler_calls == 1
    assert runtime.audit_calls == 1
    assert [kind for kind, _ in runtime.prompts] == ["compiler", "auditor"]
    assert runtime.workspaces == [
        ("compiler", tmp_path / ".evaluator-compiler"),
        ("auditor", tmp_path / ".evaluator-auditor"),
    ]
    auditor_prompt = runtime.prompts[1][1]
    assert "AUDIT_SOURCE_MARKER" in auditor_prompt
    assert '"row_count": 1' in auditor_prompt
    assert "compiler-self-probe-marker" not in auditor_prompt
    assert "private-real-order" not in auditor_prompt
    assert str(tmp_path) not in auditor_prompt
    assert {item.name for item in bundle.root.iterdir()} == {
        "audit.json",
        "evaluator.py",
        "input-profile.json",
        "manifest.json",
        "objective.md",
        "probes.json",
    }
    assert not (bundle.root / "audit.json").read_bytes().endswith(b"\n")
    assert all(
        item.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
        for item in bundle.root.iterdir()
    )
    manifest = json.loads((bundle.root / "manifest.json").read_text())
    assert len(manifest["audit_sha256"]) == 64

    assert _compile(runtime, tmp_path).fingerprint == bundle.fingerprint
    assert runtime.compiler_calls == 1
    assert runtime.audit_calls == 1


def test_agent_loop_history_and_tools_are_excluded_from_both_bundle_turns(
    tmp_path: Path,
) -> None:
    transcript = SessionTranscript(tmp_path / "prior-session.jsonl")
    transcript.append({"role": "user", "content": "PRIOR_SESSION_SECRET"})
    transcript.append({"role": "assistant", "content": "PRIOR_COMPILER_PROBES"})
    model = IsolatedAuditModel()
    runtime = AgentLoopRuntime(
        model,
        session_history=True,
        transcript=transcript,
        system_prompt="CUSTOM_SESSION_SECRET",
    )

    _compile(runtime, tmp_path)

    assert len(model.requests) == 2
    compiler_messages, compiler_tools = model.requests[0]
    auditor_messages, auditor_tools = model.requests[1]
    assert [message["role"] for message in compiler_messages] == ["system", "user"]
    assert [message["role"] for message in auditor_messages] == ["system", "user"]
    assert compiler_tools == ()
    assert auditor_tools == ()
    assert "PRIOR_SESSION_SECRET" not in json.dumps(model.requests)
    assert "PRIOR_COMPILER_PROBES" not in json.dumps(model.requests)
    assert "CUSTOM_SESSION_SECRET" not in json.dumps(model.requests)
    assert "compiler-self-probe-marker" not in json.dumps(auditor_messages)
    assert transcript.load() == [
        {"role": "user", "content": "PRIOR_SESSION_SECRET"},
        {"role": "assistant", "content": "PRIOR_COMPILER_PROBES"},
    ]


def test_independent_audit_rejects_weak_evaluator_after_self_tests_pass(
    tmp_path: Path,
) -> None:
    runtime = AuditRuntime(source=WEAK_EVALUATOR)

    with pytest.raises(EvaluatorBundleError, match="audit.*wrong validity"):
        _compile(runtime, tmp_path)

    assert runtime.compiler_calls == 1
    assert runtime.audit_calls == 1
    assert not (tmp_path / "evaluator-bundle").exists()


def test_conversational_search_never_generates_when_audit_fails(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = AuditRuntime(source=WEAK_EVALUATOR)
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    orders = tmp_path / "orders.csv"
    orders.write_text("id\nprivate-real-order\n", encoding="utf-8")

    assert main(
        [
            "solve",
            "assign every order once",
            "--runtime",
            "subprocess",
            "--input",
            str(orders),
            "--evolve",
            "--compile-evaluator",
            "--json",
            "--home",
            str(tmp_path / "home"),
        ]
    ) == 2
    assert "audit constraint probe" in capsys.readouterr().err
    assert runtime.compiler_calls == 1
    assert runtime.audit_calls == 1
    assert runtime.generation_calls == 0


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("malformed", "strict JSON"),
        ("coverage", "audit constraint coverage"),
        ("unsafe-path", "probe path"),
        ("wrong-validity", "audit.*wrong validity"),
        ("score-order", "audit score order"),
    ],
)
def test_audit_response_and_executed_claims_fail_closed(
    tmp_path: Path, mode: str, message: str
) -> None:
    audit: object = copy.deepcopy(_audit_suite())
    if mode == "malformed":
        audit = "not-json"
    elif mode == "coverage":
        audit["constraint_coverage"] = []  # type: ignore[index]
    elif mode == "unsafe-path":
        audit["probes"][0]["files"][0]["path"] = "../orders.csv"  # type: ignore[index]
    elif mode == "wrong-validity":
        audit["probes"].append(  # type: ignore[union-attr,index]
            _probe(
                "audit-false-valid",
                1,
                "id\nx\n",
                "item_id,route_id,cost\n",
            )
        )
    else:
        audit["score_order"] = [  # type: ignore[index]
            {"better": "audit-worse", "worse": "audit-better"}
        ]

    runtime = AuditRuntime(audit=audit)
    with pytest.raises(EvaluatorBundleError, match=message):
        _compile(runtime, tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


def test_audit_requires_matching_constraint_error_code(tmp_path: Path) -> None:
    source = EXACT_EVALUATOR.replace(
        'print(json.dumps(result(0, 0, "serve-all")))',
        'code = "wrong-code" if len(observed) == len(expected) else "serve-all"\n'
        "        print(json.dumps(result(0, 0, code)))",
    )
    runtime = AuditRuntime(source=source)

    with pytest.raises(EvaluatorBundleError, match="audit.*did not report serve-all"):
        _compile(runtime, tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


def test_loader_rejects_frozen_audit_tamper(tmp_path: Path) -> None:
    bundle = _compile(AuditRuntime(), tmp_path)
    audit_path = bundle.root / "audit.json"
    audit_path.chmod(0o644)
    audit_path.write_text(audit_path.read_text() + "\n", encoding="utf-8")
    audit_path.chmod(0o444)

    with pytest.raises(EvaluatorBundleError, match="audit.json digest"):
        load_evaluator_bundle(bundle.root, _contract())


def test_loader_rejects_rehashed_noncanonical_audit(tmp_path: Path) -> None:
    bundle = _compile(AuditRuntime(), tmp_path)
    bundle.root.chmod(0o755)
    audit_path = bundle.root / "audit.json"
    manifest_path = bundle.root / "manifest.json"
    audit_path.chmod(0o644)
    manifest_path.chmod(0o644)
    audit_path.write_text(audit_path.read_text() + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text())
    manifest["audit_sha256"] = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    identity = {key: value for key, value in manifest.items() if key != "bundle_sha256"}
    manifest["bundle_sha256"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    audit_path.chmod(0o444)
    manifest_path.chmod(0o444)
    bundle.root.chmod(0o555)

    with pytest.raises(EvaluatorBundleError, match="audit suite is not canonical"):
        load_evaluator_bundle(bundle.root, _contract())
