"""Compile the existing frozen bundle through the independent snapshot harness interface."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_frozen_evaluator_bundle import EVALUATOR_SOURCE, BundleRuntime, _contract, _envelope

from famou import candidate_execution_runner as runner
from famou.candidate_evaluation import _request_values
from famou.evaluator_bundle import (
    BUNDLE_FILES,
    COMPILED_BUNDLE_EVALUATOR_ID,
    SNAPSHOT_BUNDLE_PROTOCOL,
    EvaluatorBundleError,
    compile_evaluator_bundle,
    load_evaluator_bundle,
)
from famou.evolution import CandidateInputArtifact

SNAPSHOT_SOURCE = EVALUATOR_SOURCE.replace(
    '"frozen-exact-cost"', '"compiled-bundle"',
).replace(
    '    candidate = Path(sys.argv[1])\n    root = candidate.parent',
    '    request = json.loads(Path(sys.argv[1]).read_text())\n'
    '    assert request["protocol"] == "lunar-candidate-evaluation-request-v1"\n'
    '    root = Path.cwd()',
).replace('"data/raw/orders.csv"', '"inputs/orders.csv"')


def _compile(runtime, root, *, invocation="snapshot", timeout=2, **kwargs):
    target = root / "data/raw/orders.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(b"id\nprivate-real-order\n")
    content = target.read_bytes()
    descriptor = CandidateInputArtifact("data/raw/orders.csv", len(content), hashlib.sha256(content).hexdigest())
    return compile_evaluator_bundle(
        runtime, _contract(), root, inputs=(descriptor,), timeout=timeout, invocation=invocation,
        **kwargs,
    )


def _runtime(source=SNAPSHOT_SOURCE):
    return BundleRuntime(_envelope(source))


def test_snapshot_compilation_uses_108_layout_and_both_probe_suites_then_freezes(tmp_path, monkeypatch):
    runtime = _runtime()
    calls = []
    original = runner._bounded_process_bytes

    def inspect(command, **kwargs):
        root = Path(kwargs["cwd"])
        request = json.loads((root / "request.json").read_bytes())
        _request_values(request)
        assert command[-2:] == ["evaluator.py", "request.json"]
        assert request["evaluator"]["evaluator_id"] == COMPILED_BUNDLE_EVALUATOR_ID
        assert request["inputs"][0]["target"] == "orders.csv"
        assert (root / "inputs/orders.csv").is_file()
        assert (root / "output/routes.csv").is_file()
        assert not (root / "candidate.py").exists()
        assert not (root / "execution.json").exists()
        assert not (root / "data").exists()
        assert not (root / "source").exists()
        calls.append(root.parent.name)
        return original(command, **kwargs)

    monkeypatch.setattr(runner, "_bounded_process_bytes", inspect)
    bundle = _compile(runtime, tmp_path)

    assert bundle.invocation == "snapshot"
    assert runtime.bundle_calls == runtime.audit_calls == 1
    assert runtime.generation_calls == runtime.evaluator_calls == 0
    assert calls.count(".compiler-preflight") == calls.count(".audit-preflight") == 3
    assert {path.name for path in bundle.root.iterdir()} == BUNDLE_FILES
    manifest = json.loads((bundle.root / "manifest.json").read_bytes())
    assert manifest["protocol"] == SNAPSHOT_BUNDLE_PROTOCOL
    assert manifest["bundle_sha256"] == bundle.fingerprint
    assert "private-real-order" not in runtime.bundle_prompts[0] + runtime.audit_prompts[0]
    assert "lunar-candidate-evaluation-request-v1" in runtime.bundle_prompts[0]
    assert "receives a candidate path" not in runtime.bundle_prompts[0]
    assert "valid-low-cost" not in runtime.audit_prompts[0]
    assert not list(bundle.root.glob(".*-preflight"))


def test_snapshot_resume_only_loads_same_frozen_mode_and_rechecks_input_bytes(tmp_path, monkeypatch):
    runtime = _runtime()
    bundle = _compile(runtime, tmp_path)
    before = {path.name: path.read_bytes() for path in bundle.root.iterdir()}
    monkeypatch.setattr(runner, "_bounded_process_bytes", lambda *a, **k: pytest.fail("resume reran probes"))

    assert _compile(runtime, tmp_path) == bundle
    assert load_evaluator_bundle(bundle.root, _contract(), invocation="snapshot", timeout=2) == bundle
    assert runtime.bundle_calls == runtime.audit_calls == 1
    assert {path.name: path.read_bytes() for path in bundle.root.iterdir()} == before
    (tmp_path / "data/raw/orders.csv").write_bytes(b"id\nchanged-real-order\n")
    with pytest.raises(EvaluatorBundleError, match="input profile digest"):
        _compile(runtime, tmp_path)
    assert runtime.bundle_calls == runtime.audit_calls == 1


def test_snapshot_compiler_and_auditor_probes_preserve_process_ownership_callbacks(tmp_path):
    events = []
    runtime = _runtime()
    callbacks = {
        "process_observer": lambda pid, pgid: events.append(("observed", pid, pgid)),
        "process_released": lambda pid, pgid: events.append(("released", pid, pgid)),
    }

    bundle = _compile(runtime, tmp_path, **callbacks)

    assert bundle.invocation == "snapshot"
    # Compiler and independent auditor each execute three synthetic probes.
    assert len(events) == 2 * 3 * 2
    for registered, released in zip(events[::2], events[1::2], strict=True):
        assert registered[0] == "observed"
        assert registered[1] > 0
        assert registered[1] == registered[2]
        assert released == ("released", registered[1], registered[2])

    events.clear()
    assert _compile(runtime, tmp_path, **callbacks) == bundle
    assert events == []


@pytest.mark.parametrize("invocation", ["candidate", "snapshot"])
def test_frozen_invocation_modes_cannot_be_reinterpreted_or_recompiled(tmp_path, invocation):
    runtime = _runtime(EVALUATOR_SOURCE if invocation == "candidate" else SNAPSHOT_SOURCE)
    bundle = _compile(runtime, tmp_path, invocation=invocation)
    other = "snapshot" if invocation == "candidate" else "candidate"
    with pytest.raises(EvaluatorBundleError, match="protocol"):
        load_evaluator_bundle(bundle.root, _contract(), invocation=other)
    with pytest.raises(EvaluatorBundleError, match="protocol"):
        _compile(runtime, tmp_path, invocation=other)
    assert runtime.bundle_calls == runtime.audit_calls == 1
    if invocation == "snapshot":
        with pytest.raises(EvaluatorBundleError, match="requires independent"):
            bundle(tmp_path / "candidate.py", _contract())


@pytest.mark.parametrize("malformed", ["identity", "extra", "missing", "boolean", "duplicate", "nonfinite"])
def test_snapshot_preflight_uses_strict_108_report_parser(tmp_path, monkeypatch, malformed):
    payload = {"schema_version": "1", "evaluator_id": "compiled-bundle", "validity": 1,
               "quality": 1.0, "combined_score": 1.0, "detailed_scores": {}, "error_info": []}
    if malformed == "identity":
        payload["evaluator_id"] = "different"
    elif malformed == "extra":
        payload["producer_score"] = 99
    elif malformed == "missing":
        del payload["schema_version"]
    elif malformed == "boolean":
        payload["validity"] = True
    elif malformed == "nonfinite":
        payload["combined_score"] = float("nan")
    raw = json.dumps(payload).encode()
    if malformed == "duplicate":
        raw = raw[:-1] + b', "validity": 1}'
    monkeypatch.setattr(runner, "_bounded_process_bytes", lambda *a, **k: (raw, b"", "succeeded", 0, None))
    with pytest.raises(EvaluatorBundleError, match="snapshot evaluator preflight failed"):
        _compile(_runtime(), tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize("changed", ["input", "output", "request", "harness", "extra_file", "extra_directory"])
def test_snapshot_preflight_rejects_evaluator_visible_tree_mutation(tmp_path, monkeypatch, changed):
    original = runner._bounded_process_bytes

    def mutate(command, **kwargs):
        result = original(command, **kwargs)
        root = Path(kwargs["cwd"])
        if changed == "extra_directory":
            (root / "unexpected").mkdir()
        else:
            path = {"input": "inputs/orders.csv", "output": "output/routes.csv",
                    "request": "request.json", "harness": "evaluator.py", "extra_file": "unexpected"}[changed]
            (root / path).write_bytes(b"changed")
        return result

    monkeypatch.setattr(runner, "_bounded_process_bytes", mutate)
    with pytest.raises(EvaluatorBundleError, match="snapshot evaluator preflight failed"):
        _compile(_runtime(), tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize("behavior", ["timeout", "overflow"])
def test_snapshot_preflight_enforces_bounded_process_limits(tmp_path, behavior):
    source = ('def main():\n    while True:\n        pass\n' if behavior == "timeout" else
              'def main():\n    print("x" * 32769)\n')
    source += '\nif __name__ == "__main__":\n    main()\n'
    with pytest.raises(EvaluatorBundleError, match="exceeded its limits"):
        _compile(_runtime(source), tmp_path, timeout=0.05 if behavior == "timeout" else 2)
    assert not (tmp_path / "evaluator-bundle").exists()


def test_legacy_candidate_path_evaluator_is_not_accepted_as_snapshot_harness(tmp_path):
    with pytest.raises(EvaluatorBundleError, match="snapshot evaluator process failed"):
        _compile(_runtime(EVALUATOR_SOURCE), tmp_path)
    assert not (tmp_path / "evaluator-bundle").exists()


def test_snapshot_probe_cannot_introduce_undeclared_inputs(tmp_path):
    runtime = _runtime()
    runtime.envelope["probes"][0]["files"].append({"path": "data/raw/extra", "content": "secret"})
    with pytest.raises(EvaluatorBundleError, match="undeclared files"):
        _compile(runtime, tmp_path)
    assert runtime.audit_calls == 0
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize("stage", ["compiler", "auditor"])
@pytest.mark.parametrize("failure", ["order", "validity"])
def test_snapshot_compiler_and_independent_auditor_enforce_probe_claims(tmp_path, stage, failure):
    runtime = _runtime()

    def change(suite):
        if failure == "order":
            order = suite["score_order"][0]
            order["better"], order["worse"] = order["worse"], order["better"]
        else:
            invalid = next(probe for probe in suite["probes"] if probe["expected_validity"] == 0)
            valid = next(probe for probe in suite["probes"] if probe["expected_validity"] == 1)
            invalid["files"] = valid["files"]
        return suite

    if stage == "compiler":
        change(runtime.envelope)
    else:
        original = runtime.run

        def audit(prompt, workspace, timeout=None):
            result = original(prompt, workspace, timeout)
            if "adversarial evaluator auditor" in prompt:
                return type(result)(json.dumps(change(json.loads(result.text))))
            return result

        runtime.run = audit
    with pytest.raises(EvaluatorBundleError, match="score order|wrong validity"):
        _compile(runtime, tmp_path)
    assert runtime.bundle_calls == 1
    assert runtime.audit_calls == (1 if stage == "auditor" else 0)
    assert not (tmp_path / "evaluator-bundle").exists()


@pytest.mark.parametrize("invocation", ["unknown", None, True])
def test_unknown_invocation_fails_before_compiler_or_workspace(tmp_path, invocation):
    runtime = _runtime()
    root = tmp_path / "absent"
    with pytest.raises(ValueError, match="invocation"):
        compile_evaluator_bundle(runtime, _contract(), root, invocation=invocation)
    assert runtime.bundle_calls == runtime.audit_calls == 0
    assert not root.exists()
