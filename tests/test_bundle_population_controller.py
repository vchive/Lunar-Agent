"""Controller selection and portable delivery of real multi-file population candidates."""

from __future__ import annotations

import hashlib
import json

import pytest
from test_bundle_population import MAIN_SOURCE, build_context, draft_for_score

from lunar_evolution.bundle_delivery import inspect_bundle_delivery, publish_bundle_delivery
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.evolution import CandidateArchive, CandidateDraft, EvolutionError
from lunar_evolution.runtime import MockRuntime


def _completed(tmp_path, generate=None):
    context = build_context(tmp_path, generate)
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    run = controller.create_evolution_run(context.contract, workspace=context.workspace)
    settled, result = controller.run_evolution(
        run.id, context.contract, context.generate, context.evaluate, context.config,
        bundle_pipeline=context.bundle_pipeline,
    )
    assert settled.status.value == "succeeded"
    destination = tmp_path / "deliveries"
    destination.mkdir()
    return context, controller, settled, result, destination


def _calls(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("count")}


def test_controller_delivers_selected_bundle_scored_output_and_report_without_execution(tmp_path):
    context, controller, run, result, destination = _completed(tmp_path)
    before = _calls(context.workspace)
    assert len(before) == 4 and set(before.values()) == {b"x"}
    delivery = controller.deliver_bundle_evolution(run.id, destination)
    assert delivery.delivery_path.parent == destination
    assert (delivery.delivery_path / "source/solve/main.py").read_text() == MAIN_SOURCE
    assert (delivery.delivery_path / "source/solve/helper.py").read_text().endswith("return 9\n")
    assert json.loads((delivery.delivery_path / "output/result.json").read_bytes())["value"] == 9
    report = json.loads((delivery.delivery_path / "evaluation/report.json").read_bytes())
    assert report["combined_score"] == 9 and report["validity"] == 1
    candidate = CandidateArchive(context.workspace).best()
    metadata = delivery.to_dict()
    assert metadata["observation"] == "evaluation-time"
    assert metadata["identity"] == {
        "candidate_id": result.best_candidate_id,
        "contract_sha256": context.contract.digest(),
        "bundle_sha256": candidate.bundle_evidence["bundle_sha256"],
        "receipt_sha256": candidate.receipt_sha256,
        "evaluation_sha256": candidate.bundle_evidence["evaluation_sha256"],
    }
    assert str(tmp_path) not in json.dumps(metadata)
    assert inspect_bundle_delivery(
        delivery.delivery_path, expected_delivery_sha256=delivery.digest(),
    ) == delivery
    second = controller.deliver_bundle_evolution(run.id, destination)
    assert second.delivery_path != delivery.delivery_path
    assert second.digest() == delivery.digest()
    assert _calls(context.workspace) == before
    assert not (context.workspace / "evolution/materialization").exists()


def test_controller_bundle_terminal_resume_preserves_v2_artifact_index(tmp_path):
    context, controller, run, result, destination = _completed(tmp_path)
    del destination
    before = _calls(context.workspace)
    rows = controller.store.list_artifacts(run.id)
    sidecars = [row for row in rows if row["kind"] in {
        "evolution_candidate_record", "evolution_candidate_receipt",
    }]
    assert len(sidecars) == 8
    for row in sidecars:
        raw = (context.workspace / row["path"]).read_bytes()
        assert row["sha256"] == hashlib.sha256(raw).hexdigest()
        if row["kind"] == "evolution_candidate_receipt":
            assert json.loads(raw)["schema_version"] == "2"

    def forbidden(*args):
        del args
        pytest.fail("terminal resume must not generate or evaluate")

    _, resumed = controller.run_evolution(
        run.id, context.contract, forbidden, forbidden, context.config, resume=True,
        bundle_pipeline=context.bundle_pipeline,
    )
    assert resumed == result
    assert controller.store.list_artifacts(run.id) == rows
    assert _calls(context.workspace) == before


@pytest.mark.parametrize("changed", ["helper", "snapshot", "report", "receipt", "state", "result", "contract"])
def test_bundle_delivery_refuses_changed_selection_or_evidence_before_allocation(tmp_path, changed):
    context, controller, run, result, destination = _completed(tmp_path)
    del result
    candidate = CandidateArchive(context.workspace).best()
    source = context.workspace / candidate.code_path
    evaluation = context.workspace / candidate.bundle_evidence["evaluation_path"]
    paths = {
        "helper": source.parent / "helper.py",
        "snapshot": evaluation / "output/result.json",
        "report": evaluation / "report.json",
        "receipt": source.parent / "receipt.json",
        "state": context.workspace / "evolution/state.json",
        "result": context.workspace / "evolution/result.json",
        "contract": context.workspace / "evolution/contract.json",
    }
    paths[changed].write_bytes(paths[changed].read_bytes() + b" ")
    before = _calls(context.workspace)
    with pytest.raises((EvolutionError, ValueError)):
        controller.deliver_bundle_evolution(run.id, destination)
    assert list(destination.iterdir()) == []
    assert _calls(context.workspace) == before


def test_bundle_delivery_uses_retained_scored_output_after_execution_output_changes(tmp_path):
    context, controller, run, result, destination = _completed(tmp_path)
    del result
    candidate = CandidateArchive(context.workspace).best()
    evaluation = context.workspace / candidate.bundle_evidence["evaluation_path"]
    expected = (evaluation / "output/result.json").read_bytes()
    # The retained execution tree is not the output authority after independent evaluation.
    for path in context.workspace.rglob("output/result.json"):
        if path != evaluation / "output/result.json" and "evaluation.json" not in {
            item.name for item in path.parent.parent.iterdir()
        }:
            path.write_bytes(b'{"value":99999}')
    delivery = controller.deliver_bundle_evolution(run.id, destination)
    assert (delivery.delivery_path / "output/result.json").read_bytes() == expected


def test_bundle_delivery_requires_terminal_success(tmp_path):
    context = build_context(tmp_path)
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    run = controller.create_evolution_run(context.contract, workspace=context.workspace)
    with pytest.raises(EvolutionError, match="requires_successful_run"):
        controller.deliver_bundle_evolution(run.id, tmp_path)
    with pytest.raises(EvolutionError, match="requires_successful_run"):
        controller.deliver_bundle_evolution("missing", tmp_path)


def test_delivery_destination_cannot_modify_retained_evaluation_tree(tmp_path):
    context, controller, run, _, _ = _completed(tmp_path)
    selected = CandidateArchive(context.workspace).best()
    evaluation = context.workspace / selected.bundle_evidence["evaluation_path"]
    before = {path.relative_to(evaluation).as_posix(): path.read_bytes()
              for path in evaluation.rglob("*") if path.is_file()}
    with pytest.raises(EvolutionError, match="destination_conflict"):
        controller.deliver_bundle_evolution(run.id, evaluation)
    assert {path.relative_to(evaluation).as_posix(): path.read_bytes()
            for path in evaluation.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("changed", ["source", "output", "manifest", "extra", "symlink", "missing"])
def test_inspect_bundle_delivery_rejects_modified_copy(tmp_path, changed):
    _, controller, run, _, destination = _completed(tmp_path)
    delivery = controller.deliver_bundle_evolution(run.id, destination)
    root = delivery.delivery_path
    if changed == "extra":
        (root / "extra.txt").write_text("extra")
    elif changed == "missing":
        (root / "source/solve/helper.py").unlink()
    elif changed == "symlink":
        target = root / "source/solve/helper.py"
        content = target.read_bytes()
        target.unlink()
        outside = tmp_path / "helper.py"
        outside.write_bytes(content)
        target.symlink_to(outside)
    else:
        target = root / {
            "source": "source/solve/helper.py", "output": "output/result.json",
            "manifest": "delivery.json",
        }[changed]
        target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        inspect_bundle_delivery(root, expected_delivery_sha256=delivery.digest())


def test_delivery_publication_write_failure_retains_incomplete_copy(tmp_path, monkeypatch):
    from lunar_evolution.bundle_delivery import PrivateTree

    identity = {key: "a" * 64 for key in (
        "contract_sha256", "bundle_sha256", "receipt_sha256", "evaluation_sha256",
    )}
    identity["candidate_id"] = "candidate-0001"
    original = PrivateTree.write

    def fail_completion(self, path, content):
        if path == "delivery.json":
            raise OSError("fixture")
        return original(self, path, content)

    monkeypatch.setattr(PrivateTree, "write", fail_completion)
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        publish_bundle_delivery(tmp_path, identity=identity, materials={
            "source/main.py": b"pass\n", "source-bundle.json": b"{}",
            "evaluation/report.json": b"{}",
        })
    retained = list(tmp_path.iterdir())
    assert len(retained) == 1
    assert (retained[0] / "source/main.py").read_bytes() == b"pass\n"
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        inspect_bundle_delivery(retained[0])


def test_delivery_supports_all_source_input_output_files_with_long_paths(tmp_path):
    from lunar_evolution.algorithm import MAX_OUTPUTS
    from lunar_evolution.candidate_bundle import MAX_CANDIDATE_BUNDLE_FILES
    from lunar_evolution.candidate_execution import MAX_EXECUTION_INPUTS

    # Both source bundles and input declarations allow 64 long paths independently. Combining
    # those with 32 outputs must retain all 165 files, even when their manifest exceeds 128 KiB.
    long_directory = "/".join(["d" * 240] * 4)
    materials = {
        f"{namespace}/{long_directory}/file-{index:02}.txt": f"{namespace}/{index}".encode()
        for namespace, count in (
            ("source", MAX_CANDIDATE_BUNDLE_FILES),
            ("inputs", MAX_EXECUTION_INPUTS),
            ("output", MAX_OUTPUTS),
        )
        for index in range(count)
    }
    materials.update({
        "source-bundle.json": b"{}", "contract.json": b"{}",
        "evaluation/spec.json": b"{}", "evaluation/evaluator.py": b"pass\n",
        "evaluation/report.json": b"{}",
    })
    identity = {key: "a" * 64 for key in (
        "contract_sha256", "bundle_sha256", "receipt_sha256", "evaluation_sha256",
    )}
    identity["candidate_id"] = "candidate-0001"
    result = publish_bundle_delivery(tmp_path, identity=identity, materials=materials)
    assert len(result.to_dict()["files"]) == 165
    assert (result.delivery_path / "delivery.json").stat().st_size > 128 * 1024
    assert result.to_dict()["files"] == {
        name: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in materials.items()
    }
    assert inspect_bundle_delivery(
        result.delivery_path, expected_delivery_sha256=result.digest(),
    ) == result
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        publish_bundle_delivery(tmp_path, identity=identity, materials={
            **materials, "source/one-too-many.py": b"pass\n",
        })
    assert list(tmp_path.iterdir()) == [result.delivery_path]


def test_delivery_preserves_interruption_when_tree_close_also_fails(tmp_path, monkeypatch):
    from lunar_evolution.bundle_delivery import PrivateTree

    original_write, original_close = PrivateTree.write, PrivateTree.close

    def interrupt_completion(self, path, content):
        if path == "delivery.json":
            raise KeyboardInterrupt
        return original_write(self, path, content)

    def close_with_error(self):
        original_close(self)
        raise OSError("fixture close failure")

    monkeypatch.setattr(PrivateTree, "write", interrupt_completion)
    monkeypatch.setattr(PrivateTree, "close", close_with_error)
    identity = {key: "a" * 64 for key in (
        "contract_sha256", "bundle_sha256", "receipt_sha256", "evaluation_sha256",
    )}
    identity["candidate_id"] = "candidate-0001"
    with pytest.raises(KeyboardInterrupt):
        publish_bundle_delivery(tmp_path, identity=identity, materials={
            "source/main.py": b"pass\n", "source-bundle.json": b"{}",
            "evaluation/report.json": b"{}",
        })
    retained = list(tmp_path.iterdir())
    assert len(retained) == 1 and not (retained[0] / "delivery.json").exists()
    with pytest.raises(EvolutionError, match="bundle_delivery_invalid"):
        inspect_bundle_delivery(retained[0])


def test_delivery_accepts_success_after_recoverable_candidate_failures(tmp_path):
    failed = CandidateDraft.from_files(
        {"solve/main.py": "raise SystemExit(7)\n", "solve/helper.py": "unused = True\n"},
        entrypoint="solve/main.py",
    )
    proposals = iter((
        failed, draft_for_score(2), failed, draft_for_score(9),
    ))
    context, controller, run, result, destination = _completed(
        tmp_path, generate=lambda request: next(proposals),
    )
    assert run.status.value == "succeeded" and result.status == "completed"
    assert result.error == "offspring_attempt_failed" and result.best_score == 9
    assert [outcome.code for outcome in CandidateArchive(context.workspace).offspring_outcomes()] == [
        "candidate_failed", "evaluated",
    ]
    before = _calls(context.workspace)
    state_before = (context.workspace / "evolution/state.json").read_bytes()
    delivery = controller.deliver_bundle_evolution(run.id, destination)
    assert json.loads((delivery.delivery_path / "output/result.json").read_bytes())["value"] == 9
    assert (context.workspace / "evolution/state.json").read_bytes() == state_before
    assert _calls(context.workspace) == before
    assert json.loads((context.workspace / "evolution/result.json").read_bytes())["error"] == "offspring_attempt_failed"
