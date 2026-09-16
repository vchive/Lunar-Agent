"""Source checks survive the automatic solve, ranking, delivery and resume path."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_bundle_population import draft_for_score
from test_conversational_automatic_bundle import automatic_setup
from test_conversational_bundle import counts

from famou import candidate_evaluation, cli
from famou.algorithm import AlgorithmProblemContract
from famou.bundle_delivery import inspect_bundle_delivery
from famou.candidate_evaluation import inspect_candidate_evaluation
from famou.config import Config
from famou.evolution import CandidateArchive
from famou.runtime import RuntimeResult
from famou.source_constraints import validate_source_check_evidence
from famou.store import Store


def _source_aware_setup(tmp_path, monkeypatch):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    payload = runtime.contract.to_dict()
    payload["hard_constraints"].append({
        "id": "two-files", "description": "Deliver at least two Python source files.",
        "source": "user_confirmed", "verification": "independent",
        "verification_scope": "source",
        "source_check": {"kind": "python_file_count", "minimum": 2},
    })
    runtime.contract = AlgorithmProblemContract.from_dict(payload)
    original_run = runtime.run

    def generate(prompt, workspace, timeout=None):
        generation = runtime.generator_calls
        result = original_run(prompt, workspace, timeout)
        if runtime.generator_calls == generation:
            return result
        # Preserve the shared fixture's context isolation assertions and all counters.
        draft = draft_for_score((9, 2, 6, 7)[generation])
        sources = dict(draft.source_files)
        if generation == 0:
            sources = {draft.filename: sources[draft.filename].replace(
                "from helper import choose", "def choose(limit):\n    return 9",
            )}
        return RuntimeResult(json.dumps({"files": sources, "entrypoint": draft.filename}))

    monkeypatch.setattr(runtime, "run", generate)
    harness_calls = []
    real_process = candidate_evaluation._bounded_process_bytes

    def observe_harness(*args, **kwargs):
        workspace = Path(kwargs["cwd"])
        # Output scoring cannot produce or read the independent source-check evidence.
        assert not (workspace / "source-checks.json").exists()
        harness_calls.append(workspace)
        return real_process(*args, **kwargs)

    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", observe_harness)
    return runtime, args, harness_calls


def _tree_state(workspace):
    return {
        path.relative_to(workspace).as_posix(): (
            path.stat().st_ino, path.read_bytes() if path.is_file() else None,
        )
        for path in workspace.rglob("*")
    }


@pytest.mark.parametrize("resume_command", ["solve", "resume"])
def test_automatic_source_checks_exclude_high_invalid_score_and_survive_delivery_resume(
    tmp_path, monkeypatch, capsys, resume_command,
):
    runtime, args, harness_calls = _source_aware_setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "succeeded"
    assert first["evolution"]["status"] == "succeeded"
    result = first["evolution"]["result"]
    assert result["evaluated_candidates"] == 4
    assert result["valid_candidates"] == 3
    assert result["best_score"] == 7
    parent = Path(first["workspace"])
    child = parent / "evolution-run"
    archive = CandidateArchive(child)
    records = archive.records()
    assert [record.evaluation.validity for record in records] == [0, 1, 1, 1]
    assert [record.evaluation.combined_score for record in records] == [0, 2, 6, 7]
    assert records[0].evaluation.quality is None
    assert records[0].evaluation.error_info[0]["code"] == "two-files"
    assert archive.best() == records[3]
    assert result["best_candidate_id"] == records[3].candidate_id

    evaluations = []
    source_reports = []
    for index, record in enumerate(records):
        evidence = record.bundle_evidence
        root = child / evidence["evaluation_path"]
        evaluation = inspect_candidate_evaluation(
            root, expected_evaluation_sha256=evidence["evaluation_sha256"],
        )
        evaluations.append(evaluation)
        # Archive summaries intentionally sanitize local evaluator messages.
        assert evaluation.report.validity == record.evaluation.validity
        assert evaluation.report.combined_score == record.evaluation.combined_score
        assert [item["code"] for item in evaluation.report.error_info] == [
            item["code"] for item in record.evaluation.error_info
        ]
        details = evaluation.to_dict()
        assert details["output_contract_valid"] is True
        assert details["source_constraints_valid"] is (index != 0)
        assert details["harness_invoked"] is (index != 0)
        assert (root in harness_calls) is (index != 0)
        source_report = json.loads((root / "source-checks.json").read_text())
        assert validate_source_check_evidence(
            source_report, runtime.contract,
            bundle_sha256=evidence["bundle_sha256"],
            source_file_table_sha256=details["binding"]["source_file_table_sha256"],
        ) == source_report
        assert source_report["checks"] == [{
            "id": "two-files", "kind": "python_file_count", "minimum": 2,
            "observed": 1 if index == 0 else 2, "passed": index != 0,
        }]
        assert source_report["validity"] is (index != 0)
        source_reports.append((root / "source-checks.json").read_bytes())

    # The rejected candidate executed successfully and produced the highest feasible value.
    assert json.loads((evaluations[0].evaluation_path / "output/result.json").read_text())["value"] == 9
    assert len(harness_calls) == 3
    execution_counts = counts(parent)
    assert len(execution_counts) == 4 and set(execution_counts.values()) == {b"x"}
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
    assert runtime.isolated_calls == 3

    delivery = first["evolution"]["materialization"]
    assert delivery["mode"] == "bundle" and delivery["status"] == "succeeded"
    copied = parent / delivery["delivery_path"]
    package = inspect_bundle_delivery(copied)
    assert (copied / "evaluation/source-checks.json").read_bytes() == source_reports[3]
    assert json.loads((copied / "evaluation/report.json").read_text()) == records[3].evaluation.to_dict()
    assert json.loads((parent / "output/result.json").read_text())["value"] == 7
    assert (copied / "source/solve/helper.py").read_text().endswith("return 7\n")
    assert cli.main([
        "candidate-bundle", "inspect-delivery", str(copied),
        "--delivery-sha256", package.digest(), "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["delivery_sha256"] == package.digest()

    store = Store(tmp_path / "home/state.db")
    events = store.list_events(first["run_id"])
    artifacts = store.list_artifacts(first["run_id"])
    assert len([event for event in events if event["type"] == "bundle_candidate_delivered"]) == 1
    assert cli._status_payload(Config(tmp_path / "home"), first["run_id"])["evolution"]["linked"]["materialization"] == delivery
    before = _tree_state(parent)
    # A terminal resume must use the retained source evidence and the staged input.
    (tmp_path / "inputs/value").write_bytes(b"99")
    followup = (["solve", "--resume", "--run-id", first["run_id"]]
                if resume_command == "solve" else ["resume", first["run_id"]])
    assert cli.main([
        *followup, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["evolution"]["run_id"] == first["evolution"]["run_id"]
    assert resumed["evolution"]["materialization"] == delivery
    assert _tree_state(parent) == before
    assert store.list_events(first["run_id"]) == events
    assert store.list_artifacts(first["run_id"]) == artifacts
    assert counts(parent) == execution_counts
    assert len(harness_calls) == 3
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
    assert runtime.isolated_calls == 3
