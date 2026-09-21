"""Population model and archive compatibility for complete source bundles."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import replace

import pytest

import lunar_evolution.bundle_evolution as bundles
from lunar_evolution import evolution
from lunar_evolution.algorithm import AlgorithmProblemContract, EvaluationReport
from lunar_evolution.evolution import (
    Candidate,
    CandidateArchive,
    CandidateDraft,
    CandidateIntegrityAuthority,
    CandidateReceipt,
    CommandCandidateGenerator,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    GenerationRequest,
    PopulationStrategy,
)


def _report() -> EvaluationReport:
    return EvaluationReport(
        schema_version="1", evaluator_id="fixture", validity=1, quality=2.0,
        combined_score=2.0, detailed_scores={}, error_info=(),
    )


def _binding(candidate_id="candidate-0001", suffix="a"):
    source = f"evolution/candidates/{candidate_id}"
    run = f"evolution/bundle-attempts/.bundle-run-{suffix * 24}"
    return {
        "protocol": "lunar-population-bundle-v1",
        "bundle_sha256": "8" * 64,
        "bundle_path": source + "/bundle-manifest.json",
        "source_root": source,
        "run_root": run,
        "plan_sha256": "9" * 64,
        "admission_sha256": "a" * 64,
        "completion_sha256": "b" * 64,
        "evaluation_path": run + "/evaluations/.candidate-evaluation-" + "c" * 24,
        "evaluation_sha256": "d" * 64,
    }


def _authority() -> CandidateIntegrityAuthority:
    return CandidateIntegrityAuthority(
        schema_version="1", contract_sha256="2" * 64, evaluator_kind="exact_harness",
        evaluator_fingerprint="3" * 64, dependency_sha256="4" * 64,
        environment_sha256="5" * 64, runner_fingerprint="6" * 64,
        generator_fingerprint="7" * 64,
    )


def _receipt(binding=None) -> CandidateReceipt:
    fields = _authority().to_dict()
    fields.pop("schema_version")
    return CandidateReceipt.from_report(
        _report(), candidate_id="cand-000001", source_sha256="1" * 64,
        parent_id=None, generation=0, iteration=0, island_id=0, **fields,
        bundle_evidence=binding,
    )


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "bundle-models", "problem_type": "routing",
        "statement": "Find a deterministic route.",
        "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "identifier"}}],
        "decision_variables": ["order"],
        "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [],
        "success_criteria": ["All items served."], "deliverables": ["source"],
    })


def test_legacy_draft_and_receipt_keep_exact_payload_and_digest():
    draft = CandidateDraft("pass\n", "solve.py", {"family": "simple"})
    assert draft.source_files is None
    receipt = _receipt()
    assert receipt.schema_version == "1"
    assert "bundle_evidence" not in receipt.to_dict()
    assert receipt.receipt_sha256 == "218da0062c2cc507b89f89b144ae7e27286051c92a0a21b0dfec6199ec294fcd"
    assert CandidateReceipt.from_dict(receipt.to_dict()) == receipt


def test_from_files_detaches_complete_map_and_binds_helper_bytes():
    files = {"src/main.py": "import helper\n", "helper.py": "value = 1\n"}
    draft = CandidateDraft.from_files(files, "src/main.py", {"family": "bundle"})
    first = bundles.validate_bundle_draft(draft, "2" * 64)
    files["helper.py"] = "value = 9\n"
    assert draft.source == "import helper\n"
    assert draft.filename == "src/main.py"
    assert draft.source_files["helper.py"] == "value = 1\n"
    second = bundles.validate_bundle_draft(
        CandidateDraft.from_files(files, "src/main.py"), "2" * 64,
    )
    assert first.digest() != second.digest()
    assert first.entrypoint == second.entrypoint


@pytest.mark.parametrize("files,entrypoint", [
    ({}, "main.py"),
    ({"helper.py": "pass"}, "main.py"),
    ({"main.py": ""}, "main.py"),
    ({"main.py": b"pass"}, "main.py"),
    ({"main.py": "pass", "helper.py": b"pass"}, "main.py"),
    ({"main.py": "pass", "../helper.py": "pass"}, "main.py"),
    ({"main.py": "pass", "/helper.py": "pass"}, "main.py"),
    ({"main.py": "pass", "lib/a.py": "pass", "LIB/b.py": "pass"}, "main.py"),
    ({"main.py": "pass", "lib": "pass", "lib/a.py": "pass"}, "main.py"),
    ({"main.py": "pass", ".git/config": "pass"}, "main.py"),
    ({"main.py": "pass", "helper.py": "x" * (1024 * 1024 + 1)}, "main.py"),
    ({"main.py": "pass", **{f"f{i}.py": "pass" for i in range(64)}}, "main.py"),
])
def test_invalid_complete_source_maps_are_rejected(files, entrypoint):
    with pytest.raises((EvolutionError, TypeError, ValueError)):
        CandidateDraft.from_files(files, entrypoint)


def test_entrypoint_source_cannot_disagree_with_complete_map():
    with pytest.raises((EvolutionError, ValueError)):
        CandidateDraft("pass", "main.py", source_files={"main.py": "raise Exception"})


def test_mutated_draft_map_is_revalidated_before_materialization():
    draft = CandidateDraft.from_files({"main.py": "pass"}, "main.py")
    draft.source_files["main.py"] = "different"
    with pytest.raises((EvolutionError, ValueError)):
        bundles.validate_bundle_draft(draft, "2" * 64)


def test_v2_receipt_binds_detached_evidence():
    binding = _binding()
    receipt = _receipt(binding)
    assert receipt.schema_version == "2"
    assert CandidateReceipt.from_dict(receipt.to_dict()) == receipt
    original = receipt.bundle_evidence["evaluation_sha256"]
    binding["evaluation_sha256"] = "e" * 64
    assert receipt.bundle_evidence["evaluation_sha256"] == original
    changed = _receipt(binding)
    assert changed.receipt_sha256 != receipt.receipt_sha256


@pytest.mark.parametrize("mutation", ["missing", "null", "version", "digest", "unknown"])
def test_v2_receipt_cannot_drop_or_downgrade_evidence(mutation):
    value = copy.deepcopy(_receipt(_binding()).to_dict())
    if mutation == "missing":
        value.pop("bundle_evidence")
    elif mutation == "null":
        value["bundle_evidence"] = None
    elif mutation == "version":
        value["schema_version"] = "1"
    elif mutation == "digest":
        value["bundle_evidence"]["evaluation_sha256"] = "f" * 64
    else:
        value["extra"] = True
    with pytest.raises((EvolutionError, ValueError)):
        CandidateReceipt.from_dict(value)


def test_v1_receipt_rejects_even_null_extension():
    value = _receipt().to_dict()
    value["bundle_evidence"] = None
    with pytest.raises(EvolutionError, match="ordinary_candidate_receipt_invalid"):
        CandidateReceipt.from_dict(value)


def _candidate(binding=None):
    return Candidate(
        candidate_id="candidate-0001", code_path="evolution/candidates/candidate-0001/main.py",
        parent_id=None, generation=0, iteration=0, strategy="population", island_id=0,
        evaluation=_report(), source_sha256="1" * 64, receipt_sha256="2" * 64,
        integrity={}, bundle_evidence=binding,
    )


def test_candidate_extension_is_additive_and_detached():
    assert "bundle_evidence" not in _candidate().to_dict()
    binding = _binding()
    candidate = _candidate(binding)
    binding["bundle_sha256"] = "f" * 64
    assert candidate.bundle_evidence["bundle_sha256"] == "8" * 64
    assert Candidate.from_dict(candidate.to_dict()) == candidate
    with pytest.raises(ValueError):
        replace(candidate, integrity=None)


@pytest.mark.parametrize("array", [False, True])
def test_command_generator_accepts_complete_bundle_objects(tmp_path, monkeypatch, array):
    value = {"entrypoint": "src/main.py", "files": {"src/main.py": "pass", "helper.py": "x=1"},
             "metadata": {"family": "bundle"}}
    result = [value, {"source": "pass"}] if array else value
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps(result), ""))
    generated = CommandCandidateGenerator([sys.executable])(GenerationRequest(0, None, (), (), tmp_path))
    draft = generated[0] if array else generated
    assert draft.source_files == value["files"]
    assert draft.filename == "src/main.py"
    if array:
        assert generated[1].source_files is None


def test_command_generator_rejects_ambiguous_source_and_files(tmp_path, monkeypatch):
    value = {"source": "pass", "entrypoint": "main.py", "files": {"main.py": "pass"}}
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps(value), ""))
    with pytest.raises(EvolutionError):
        CommandCandidateGenerator([sys.executable])(GenerationRequest(0, None, (), (), tmp_path))


def _source_parent(workspace):
    sources = {"src/main.py": "from helper import value\n", "helper.py": "value = 1\n"}
    draft = CandidateDraft.from_files(sources, "src/main.py")
    manifest = bundles.validate_bundle_draft(draft, "2" * 64)
    binding = _binding()
    binding["bundle_sha256"] = manifest.digest()
    for name, content in sources.items():
        path = workspace / binding["source_root"] / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (workspace / binding["bundle_path"]).write_text(json.dumps(manifest.to_dict()))
    parent = replace(_candidate(binding), code_path=binding["source_root"] + "/src/main.py")
    return parent, sources


def test_actual_command_generator_receives_and_mutates_complete_parent_sources(tmp_path):
    parent, sources = _source_parent(tmp_path)
    command = tmp_path / "generator.py"
    command.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(pathlib.Path(sys.argv[-1]).read_text())\n"
        f"assert request['parent_source_files'] == {sources!r}\n"
        "updated = request['parent_source_files']\n"
        "updated['helper.py'] = 'value = 9\\n'\n"
        "print(json.dumps({'entrypoint': 'src/main.py', 'files': updated}))\n"
    )
    generated = CommandCandidateGenerator([sys.executable, str(command)])(
        GenerationRequest(1, parent, (), (parent,), tmp_path),
    )
    assert generated.source_files == {**sources, "helper.py": "value = 9\n"}
    request = json.loads((tmp_path / "evolution/external/generator/request-0001.json").read_text())
    assert request["parent_source_files"] == sources


@pytest.mark.parametrize("has_parent", [False, True])
def test_legacy_command_request_omits_parent_source_extension(tmp_path, monkeypatch, has_parent):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "pass", ""))
    parent = _candidate() if has_parent else None
    CommandCandidateGenerator([sys.executable])(GenerationRequest(0, parent, (), (), tmp_path))
    request = json.loads((tmp_path / "evolution/external/generator/request-0000.json").read_text())
    assert "parent_source_files" not in request


def test_command_generator_rejects_changed_parent_helper_before_launch(tmp_path, monkeypatch):
    parent, _ = _source_parent(tmp_path)
    (tmp_path / parent.bundle_evidence["source_root"] / "helper.py").write_text("changed")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))
    with pytest.raises(EvolutionError):
        CommandCandidateGenerator([sys.executable])(GenerationRequest(1, parent, (), (parent,), tmp_path))
    assert not calls


def _persist(archive, *, binding, candidate_id="candidate-0001", parent=None, iteration=0):
    return archive.persist(
        CandidateDraft("pass\n", "src/main.py"), candidate_id=candidate_id,
        strategy="population", iteration=iteration, generation=int(parent is not None),
        parent_id=parent, island_id=0, evaluation=_report(), integrity_authority=_authority(),
        bundle_evidence=binding,
    )


def test_archive_binds_v2_receipt_and_rechecks_bundle_during_publication(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", lambda *a, **kw: calls.append((a, kw)))
    archive = CandidateArchive(tmp_path)
    first = _persist(archive, binding=_binding())
    assert len(calls) >= 6
    assert all(call[1]["code_path"] == first.code_path for call in calls)
    assert first.source_sha256 == hashlib.sha256(b"pass\n").hexdigest()
    assert archive.read_candidate_receipt(first.candidate_id).schema_version == "2"
    assert archive.records() == [first]
    archive.validate_candidate_integrity(authority=_authority())
    second = _persist(
        archive, binding=_binding("candidate-0002", "b"), candidate_id="candidate-0002",
        parent=first.candidate_id, iteration=1,
    )
    assert archive.records() == [first, second]
    archive.validate_candidate_integrity(authority=_authority())


def test_archive_rolls_back_append_when_bundle_changes_during_publication(tmp_path, monkeypatch):
    archive = CandidateArchive(tmp_path)

    def validate(*args, **kwargs):
        if archive.archive_path.exists() and archive.archive_path.stat().st_size:
            raise EvolutionError("bundle_changed")

    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", validate)
    with pytest.raises(EvolutionError, match="bundle_changed"):
        _persist(archive, binding=_binding())
    assert archive.records() == []


@pytest.mark.parametrize("same_evaluation", [False, True])
def test_archive_rejects_reusing_physical_attempt_for_another_candidate(tmp_path, monkeypatch, same_evaluation):
    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", lambda *a, **kw: None)
    archive = CandidateArchive(tmp_path)
    first = _persist(archive, binding=_binding())
    binding = _binding("candidate-0002")
    if not same_evaluation:
        binding["evaluation_path"] = binding["run_root"] + "/evaluations/.candidate-evaluation-" + "e" * 24
    with pytest.raises(EvolutionError, match="bundle_candidate_execution_reused"):
        _persist(archive, binding=binding, candidate_id="candidate-0002",
                 parent=first.candidate_id, iteration=1)
    assert archive.records() == [first]
    assert not (archive.candidates_root / "candidate-0002").exists()


@pytest.mark.parametrize("same_evaluation", [False, True])
def test_integrity_rejects_forged_duplicate_attempt_references(tmp_path, monkeypatch, same_evaluation):
    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", lambda *a, **kw: None)
    archive = CandidateArchive(tmp_path)
    first = _persist(archive, binding=_binding())
    second = _persist(archive, binding=_binding("candidate-0002", "b"),
                      candidate_id="candidate-0002", parent=first.candidate_id, iteration=1)
    forged = _binding("candidate-0002")
    if not same_evaluation:
        forged["evaluation_path"] = forged["run_root"] + "/evaluations/.candidate-evaluation-" + "e" * 24
    second = replace(second, bundle_evidence=forged)
    with pytest.raises(EvolutionError, match="bundle_candidate_execution_reused"):
        archive.validate_candidate_integrity(authority=_authority(), records=(first, second))


def test_archive_dropped_bundle_binding_fails_integrity_even_with_matching_record(tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", lambda *a, **kw: None)
    archive = CandidateArchive(tmp_path)
    candidate = _persist(archive, binding=_binding())
    stripped = candidate.to_dict()
    stripped.pop("bundle_evidence")
    content = json.dumps(stripped) + "\n"
    archive.archive_path.write_text(content)
    (tmp_path / candidate.code_path).with_name("record.json").write_text(content)
    with pytest.raises(EvolutionError, match="ordinary_candidate_integrity_mismatch"):
        archive.validate_candidate_integrity(authority=_authority())


def test_read_only_strategy_allows_bundle_archive_but_run_requires_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", lambda *a, **kw: None)
    archive = CandidateArchive(tmp_path)
    _persist(archive, binding=_binding())
    calls = []
    context = EvolutionContext(_contract(), tmp_path, lambda req: calls.append("generate"),
                               lambda *args: calls.append("evaluate"))
    strategy = PopulationStrategy(context)
    for method in (strategy.run, strategy.resume):
        with pytest.raises(EvolutionError, match="bundle_candidate_pipeline_required"):
            method()
    assert not calls


def test_bundle_draft_without_pipeline_never_calls_legacy_evaluator(tmp_path):
    calls = []
    draft = CandidateDraft.from_files({"main.py": "pass", "helper.py": "x=1"}, "main.py")
    context = EvolutionContext(_contract(), tmp_path, lambda req: draft,
                               lambda *args: calls.append("evaluate"))
    strategy = PopulationStrategy(context)
    with pytest.raises(evolution._InitialCandidateFailure, match="candidate_failed"):
        strategy._persist(draft, iteration=0, generation=0, parent=None, island_id=0)
    assert not calls


def test_archive_cannot_silently_drop_helper_sources(tmp_path):
    draft = CandidateDraft.from_files({"main.py": "pass", "helper.py": "x=1"}, "main.py")
    archive = CandidateArchive(tmp_path)
    with pytest.raises(EvolutionError, match="bundle_candidate_evidence_required"):
        archive.persist(draft, strategy="population", iteration=0, generation=0,
                        island_id=0, evaluation=_report(), integrity_authority=_authority())
    assert archive.records() == []


def test_archive_cannot_ignore_draft_helper_bytes_even_with_evidence(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bundles, "validate_candidate_bundle_evidence", lambda *a, **kw: calls.append(kw))
    draft = CandidateDraft.from_files({"main.py": "pass", "helper.py": "x=1"}, "main.py")
    archive = CandidateArchive(tmp_path)
    with pytest.raises(EvolutionError, match="bundle_candidate_source_mismatch"):
        archive.persist(draft, strategy="population", iteration=0, generation=0,
                        island_id=0, evaluation=_report(), integrity_authority=_authority(),
                        bundle_evidence=_binding())
    assert archive.records() == []
    assert not calls


def test_bundle_pipeline_receives_full_draft_and_authority(tmp_path):
    calls = []
    candidate = _candidate(_binding())

    class Pipeline:
        def validate_context(self, context, authority):
            calls.append(("context", context, authority))

        def persist(self, strategy, draft, **lineage):
            calls.append(("persist", draft, lineage))
            return candidate

    config = EvolutionConfig(population_size=1)
    context = EvolutionContext(_contract(), tmp_path, lambda req: None, lambda *args: None,
                               config, bundle_pipeline=Pipeline())
    strategy = PopulationStrategy(context)
    draft = CandidateDraft.from_files({"main.py": "pass", "helper.py": "x=1"}, "main.py")
    assert strategy._persist(draft, iteration=0, generation=0, parent=None, island_id=0) is candidate
    assert calls[0][0] == "context"
    assert calls[0][2].contract_sha256 == context.contract.digest()
    assert calls[1][1].source_files == draft.source_files


def test_bundle_novelty_reads_helper_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "read_candidate_source_files", lambda *a: {
        "main.py": "pass", "helper.py": "special_algorithm = 17",
    })
    assert evolution._tokens(_candidate(_binding()), tmp_path) == {"pass", "special_algorithm", "17"}
