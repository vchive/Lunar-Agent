"""Source-aware selection and portable evidence remain bound without additional execution."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import test_bundle_parent_delivery as parent_fixture
from test_bundle_population import build_context, draft_for_score
from test_bundle_population_controller import _calls

from lunar_evolution.algorithm import AlgorithmProblemContract, EvaluationReport
from lunar_evolution.bundle_delivery import inspect_bundle_delivery, publish_bundle_delivery
from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import (
    CandidateArchive,
    CandidateDraft,
    EvolutionError,
    PopulationStrategy,
)
from lunar_evolution.runtime import MockRuntime
from lunar_evolution.source_constraints import MAX_SOURCE_CHECK_BYTES, source_check_evidence


def _contract(contract, *, minimum=2, scope="source", checker=True, soft=False):
    value = contract.to_dict()
    constraint = {
        "id": "python_sources", "description": "Declare the required count of lowercase .py files.",
        "source": "user_confirmed", "verification": "independent", "verification_scope": scope,
    }
    if checker:
        constraint["source_check"] = {"kind": "python_file_count", "minimum": minimum}
    value["soft_constraints" if soft else "hard_constraints"] = [constraint]
    return AlgorithmProblemContract.from_dict(value)


def _portable(tmp_path, *, minimum=2):
    context = build_context(tmp_path)
    contract = _contract(context.contract, minimum=minimum)
    sources = {"main.py": b"raise AssertionError('never import source while inspecting')\n", "empty.py": b""}
    bundle = CandidateSourceBundle(contract.digest(), "main.py", tuple(
        CandidateSourceFile(name, len(raw), hashlib.sha256(raw).hexdigest())
        for name, raw in sources.items()
    ))
    evidence = source_check_evidence(contract, bundle)
    report = EvaluationReport("1", context.bundle_pipeline.evaluator.evaluator_id, 1, 5.0, {}, ())
    materials = {"source/" + name: raw for name, raw in sources.items()}
    materials.update({
        "contract.json": canonical_json(contract.to_dict()),
        "source-bundle.json": canonical_json(bundle.to_dict()),
        "evaluation/source-checks.json": canonical_json(evidence),
        "evaluation/report.json": canonical_json(report.to_dict()),
        "evaluation/spec.json": canonical_json(context.bundle_pipeline.evaluator.to_dict()),
        "evaluation/evaluator.py": context.bundle_pipeline.harness_path.read_bytes(),
    })
    identity = {
        "candidate_id": "candidate-0001", "contract_sha256": contract.digest(),
        "bundle_sha256": bundle.digest(), "receipt_sha256": "a" * 64,
        "evaluation_sha256": "b" * 64,
    }
    destination = tmp_path / "deliveries"
    destination.mkdir()
    return destination, identity, materials


def _rewrite_package(root, *, replacements=None, removed=(), protocol=None):
    """Simulate a coherent outer-manifest rewrite, leaving independent semantic pins intact."""
    manifest_path = root / "delivery.json"
    manifest = json.loads(manifest_path.read_bytes())
    if protocol is not None:
        manifest["protocol"] = protocol
    for name in removed:
        (root / name).unlink()
        del manifest["files"][name]
    for name, raw in (replacements or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(raw)
        manifest["files"][name] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    manifest_path.write_bytes(canonical_json(manifest))


def test_portable_source_evidence_accepts_empty_python_file_and_never_executes(tmp_path):
    destination, identity, materials = _portable(tmp_path)
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    assert delivery.to_dict()["protocol"] == "lunar-bundle-delivery-source-v1"
    assert inspect_bundle_delivery(delivery.delivery_path) == delivery
    evidence = json.loads((delivery.delivery_path / "evaluation/source-checks.json").read_bytes())
    assert evidence["validity"] is True and evidence["checks"][0]["observed"] == 2
    assert (delivery.delivery_path / "source/empty.py").read_bytes() == b""


@pytest.mark.parametrize("removed", [(), ("evaluation/source-checks.json",), ("contract.json",)])
def test_portable_source_protocol_cannot_downgrade_with_source_requirements_retained(tmp_path, removed):
    destination, identity, materials = _portable(tmp_path)
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    _rewrite_package(delivery.delivery_path, removed=removed, protocol="lunar-bundle-delivery-v1")
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        inspect_bundle_delivery(delivery.delivery_path)


def test_portable_source_protocol_requires_contract_and_evidence_when_both_removed(tmp_path):
    destination, identity, materials = _portable(tmp_path)
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    _rewrite_package(delivery.delivery_path, removed=("contract.json", "evaluation/source-checks.json"))
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        inspect_bundle_delivery(delivery.delivery_path)


@pytest.mark.parametrize("opaque", [b"historical opaque contract", b"\xff", b'{"incomplete":'])
def test_legacy_delivery_preserves_opaque_contract_bytes_and_protocol(tmp_path, opaque):
    destination, identity, materials = _portable(tmp_path)
    del materials["evaluation/source-checks.json"]
    materials["contract.json"] = opaque
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    assert delivery.to_dict()["protocol"] == "lunar-bundle-delivery-v1"
    assert (delivery.delivery_path / "contract.json").read_bytes() == opaque
    assert inspect_bundle_delivery(delivery.delivery_path) == delivery


def test_source_delivery_does_not_accept_opaque_contract_bytes(tmp_path):
    destination, identity, materials = _portable(tmp_path)
    materials["contract.json"] = b"historical opaque contract"
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        publish_bundle_delivery(destination, identity=identity, materials=materials)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("changed", [
    "missing_evidence", "missing_contract", "missing_spec", "source_bytes", "extra_source",
    "missing_source", "source_manifest", "contract", "evidence_bundle", "evidence_count",
    "evidence_noncanonical", "evidence_malformed", "invalid_report", "wrong_evaluator",
])
def test_portable_source_validation_rejects_tampering_even_after_manifest_rehash(tmp_path, changed):
    destination, identity, materials = _portable(tmp_path)
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    replacements, removed = {}, []
    if changed.startswith("missing_"):
        removed.append({"missing_evidence": "evaluation/source-checks.json", "missing_contract": "contract.json",
                        "missing_spec": "evaluation/spec.json", "missing_source": "source/empty.py"}[changed])
    elif changed == "source_bytes":
        replacements["source/empty.py"] = b"# changed, still a Python file\n"
    elif changed == "extra_source":
        replacements["source/extra.py"] = b""
    elif changed == "source_manifest":
        value = json.loads(materials["source-bundle.json"])
        value["entrypoint"] = "empty.py"
        replacements["source-bundle.json"] = canonical_json(value)
    elif changed == "contract":
        value = json.loads(materials["contract.json"])
        value["statement"] += " Changed."
        replacements["contract.json"] = canonical_json(value)
    elif changed.startswith("evidence_"):
        value = json.loads(materials["evaluation/source-checks.json"])
        if changed == "evidence_bundle":
            value["bundle"]["entrypoint"] = "empty.py"
        elif changed == "evidence_count":
            value["checks"][0]["observed"] = 99
        elif changed == "evidence_malformed":
            value = {"validity": True}
        raw = canonical_json(value)
        replacements["evaluation/source-checks.json"] = raw + (b" " if changed == "evidence_noncanonical" else b"")
    else:
        value = json.loads(materials["evaluation/report.json"])
        if changed == "invalid_report":
            value.update(validity=0, combined_score=0.0, quality=None,
                         error_info=[{"code": "invalid_output", "message": "Output failed."}])
        else:
            value["evaluator_id"] = "other-evaluator"
        replacements["evaluation/report.json"] = canonical_json(value)
    _rewrite_package(delivery.delivery_path, replacements=replacements, removed=removed)
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        inspect_bundle_delivery(delivery.delivery_path)


@pytest.mark.parametrize("forge", [False, True])
def test_source_failure_cannot_be_published_with_a_passing_output_report(tmp_path, forge):
    destination, identity, materials = _portable(tmp_path, minimum=3)
    if forge:
        value = json.loads(materials["evaluation/source-checks.json"])
        value["validity"] = True
        value["checks"][0].update(observed=3, passed=True)
        materials["evaluation/source-checks.json"] = canonical_json(value)
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        publish_bundle_delivery(destination, identity=identity, materials=materials)
    assert list(destination.iterdir()) == []


def test_source_evidence_cannot_be_attached_to_a_legacy_contract(tmp_path):
    destination, identity, materials = _portable(tmp_path)
    value = json.loads(materials["contract.json"])
    value["hard_constraints"] = []
    materials["contract.json"] = canonical_json(value)
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        publish_bundle_delivery(destination, identity=identity, materials=materials)


def test_source_aware_delivery_supports_all_166_declared_materials(tmp_path):
    from lunar_evolution.algorithm import MAX_OUTPUTS
    from lunar_evolution.candidate_bundle import MAX_CANDIDATE_BUNDLE_FILES
    from lunar_evolution.candidate_execution import MAX_EXECUTION_INPUTS

    destination, identity, materials = _portable(tmp_path)
    contract = AlgorithmProblemContract.from_dict(json.loads(materials["contract.json"]))
    for index in range(MAX_CANDIDATE_BUNDLE_FILES - 2):
        materials[f"source/extra-{index}.py"] = b""
    bundle = CandidateSourceBundle(contract.digest(), "main.py", tuple(
        CandidateSourceFile(name.removeprefix("source/"), len(raw), hashlib.sha256(raw).hexdigest())
        for name, raw in materials.items() if name.startswith("source/")
    ))
    materials["source-bundle.json"] = canonical_json(bundle.to_dict())
    materials["evaluation/source-checks.json"] = canonical_json(source_check_evidence(contract, bundle))
    identity["bundle_sha256"] = bundle.digest()
    for prefix, count in (("inputs", MAX_EXECUTION_INPUTS), ("output", MAX_OUTPUTS)):
        materials.update({f"{prefix}/file-{index}.txt": b"0" for index in range(count)})
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    assert len(delivery.to_dict()["files"]) == 166
    assert inspect_bundle_delivery(delivery.delivery_path) == delivery
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        publish_bundle_delivery(destination, identity=identity, materials={**materials, "source/excess.py": b""})
    assert list(destination.iterdir()) == [delivery.delivery_path]


def test_portable_source_delivery_accepts_evidence_larger_than_bundle_limit(tmp_path):
    destination, identity, materials = _portable(tmp_path)
    base = AlgorithmProblemContract.from_dict(json.loads(materials["contract.json"]))
    contract = replace(base, hard_constraints=tuple(
        replace(base.hard_constraints[0], id="count-" + "x" * 440 + str(index)) for index in range(64)
    ))
    paths = ["/".join(['"' * 200] * 4) + "/" + str(index) + ".py" for index in range(64)]
    bundle = CandidateSourceBundle(contract.digest(), paths[0], tuple(
        CandidateSourceFile(name, 0, hashlib.sha256(b"").hexdigest()) for name in paths
    ))
    evidence = canonical_json(source_check_evidence(contract, bundle), maximum=MAX_SOURCE_CHECK_BYTES)
    assert 128 * 1024 < len(evidence) <= MAX_SOURCE_CHECK_BYTES
    materials = {name: raw for name, raw in materials.items() if not name.startswith("source/")}
    materials.update({"source/" + name: b"" for name in paths})
    materials.update({"source-bundle.json": canonical_json(bundle.to_dict()),
                      "contract.json": canonical_json(contract.to_dict()),
                      "evaluation/source-checks.json": evidence})
    identity.update(contract_sha256=contract.digest(), bundle_sha256=bundle.digest())
    delivery = publish_bundle_delivery(destination, identity=identity, materials=materials)
    assert inspect_bundle_delivery(delivery.delivery_path) == delivery
    assert (delivery.delivery_path / "evaluation/source-checks.json").read_bytes() == evidence


def _selection_context(tmp_path):
    proposals = iter(((10, False), (2, True), (999, True), (9, True)))

    def generate(_):
        score, with_empty_file = next(proposals)
        draft = draft_for_score(score)
        sources = dict(draft.source_files)
        if with_empty_file:
            sources["solve/empty.py"] = ""
        return CandidateDraft.from_files(sources, entrypoint=draft.filename)

    context = build_context(tmp_path, generate)
    return replace(context, contract=_contract(context.contract, minimum=3))


def test_population_selects_final_source_and_output_validity_and_terminal_resume_is_read_only(tmp_path):
    context = _selection_context(tmp_path)
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    run = controller.create_evolution_run(context.contract, workspace=context.workspace)
    settled, result = controller.run_evolution(
        run.id, context.contract, context.generate, context.evaluate, context.config,
        bundle_pipeline=context.bundle_pipeline,
    )
    assert settled.status.value == "succeeded" and result.best_score == 9
    archive = CandidateArchive(context.workspace)
    candidates = archive.records()
    assert [candidate.evaluation.validity for candidate in candidates] == [0, 1, 0, 1]
    assert [candidate.evaluation.combined_score for candidate in candidates] == [0, 2, 0, 9]
    assert candidates[0].evaluation.error_info[0]["code"] == "python_sources"
    assert result.best_candidate_id == candidates[-1].candidate_id
    before_calls = _calls(context.workspace)
    assert len(before_calls) == 4

    def forbidden(*_args, **_kwargs):
        pytest.fail("terminal resume and delivery must not generate, execute or evaluate")

    _, resumed = controller.run_evolution(
        run.id, context.contract, forbidden, forbidden, context.config, resume=True,
        bundle_pipeline=context.bundle_pipeline,
    )
    assert resumed == result
    destination = tmp_path / "deliveries"
    destination.mkdir()
    delivery = controller.deliver_bundle_evolution(run.id, destination)
    assert inspect_bundle_delivery(delivery.delivery_path) == delivery
    assert json.loads((delivery.delivery_path / "evaluation/source-checks.json").read_bytes())["validity"] is True
    assert json.loads((delivery.delivery_path / "evaluation/report.json").read_bytes())["combined_score"] == 9
    assert _calls(context.workspace) == before_calls


def test_parent_delivery_retains_source_evidence_and_reuses_terminal_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(parent_fixture, "build_context", _selection_context)
    fixture = parent_fixture._completed(tmp_path)
    context, controller, parent, _child, _result = fixture
    before = _calls(context.workspace)
    payload = parent_fixture._finish(fixture)
    evidence_path = payload["delivery_path"] + "/evaluation/source-checks.json"
    evidence = json.loads((Path(parent.workspace) / evidence_path).read_bytes())
    assert evidence["validity"] is True and evidence["checks"][0]["observed"] == 3
    assert any(row["path"] == evidence_path for row in controller.store.list_artifacts(parent.id))
    assert parent_fixture._finish(fixture) == payload
    controller.deliver(parent.id)
    assert _calls(context.workspace) == before


@pytest.mark.parametrize("kind", ["source_without_check", "execution", "soft_source"])
def test_explicit_pipeline_rejects_unsupported_scopes_before_generation(tmp_path, kind):
    def forbidden(_):
        pytest.fail("unsupported source requirements must fail before candidate generation")

    context = build_context(tmp_path, forbidden)
    contract = _contract(context.contract, checker=kind == "soft_source",
                         soft=kind == "soft_source", scope="execution" if kind == "execution" else "source")
    context = replace(context, contract=contract)
    with pytest.raises(EvolutionError, match="unsupported_constraints"):
        PopulationStrategy(context).run()
    assert _calls(context.workspace) == {}
