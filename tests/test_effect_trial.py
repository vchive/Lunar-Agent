import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from famou.cli import _model_profile_digest, main
from famou.effect_trial import (
    MAX_COST_MICROS,
    MAX_TOKENS,
    EffectTrialConfig,
    EffectTrialError,
    EffectTrialRunner,
    TrialBaseline,
)
from famou.profiles import ModelProfile

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
OBJECT_A = f"sha256:{HEX_A}"
OBJECT_B = f"sha256:{HEX_B}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_failed_subject_diagnostic_is_collected_without_harness_or_score(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls = []

    def executor(command, *, cwd, env, timeout):
        calls.append(command)
        request_path = Path(command[-1])
        request = json.loads(request_path.read_text())
        assert request["mode"] == "normal", "harness must not run after subject failure"
        diagnostic = {
            "schema_version": "1", "kind": "subject_failure", "mode": "normal",
            "request_sha256": _sha(request_path), "run_index": request["run_index"],
            "round_index": None, "stage": "model", "code": "model_http_failed",
            "model_turns": 0, "tool_steps": 0, "http_status": 429,
        }
        (cwd / "receipt.failure.json").write_text(json.dumps(diagnostic))
        # Collection must use the pre-call identity, not this changed request.
        request_path.write_text("{}")
        return subprocess.CompletedProcess(command, 2)

    report = _runner(tmp_path, fixture, executor=executor).run().to_dict()
    assert len(calls) == 3
    for run in report["cases"][0]["runs"]:
        assert run["error_code"] == "process_nonzero_exit"
        assert run["ready"] is False and run["overall_score"] is None
        diagnostic = json.loads((
            tmp_path / "trial" / run["attempt"] / "diagnostics" / "subject-failure.json"
        ).read_text())
        assert diagnostic["code"] == "model_http_failed"
        assert diagnostic["run_index"] == run["run_index"]


@pytest.mark.parametrize("invalid", ["missing", "json", "oversized", "score", "stale", "symlink", "fifo", "destination"])
def test_bad_diagnostics_preserve_process_failure_and_score_boundary(tmp_path: Path, invalid: str) -> None:
    fixture = _fixture(tmp_path)
    calls = []

    def executor(command, *, cwd, env, timeout):
        calls.append(command)
        request_path = Path(command[-1])
        request = json.loads(request_path.read_text())
        assert request["mode"] == "normal"
        payload = {
            "schema_version": "1", "kind": "subject_failure", "mode": "normal",
            "request_sha256": _sha(request_path), "run_index": request["run_index"],
            "round_index": None, "stage": "model", "code": "model_failed",
            "model_turns": 0, "tool_steps": 0, "http_status": None,
        }
        sidecar = cwd / "receipt.failure.json"
        if invalid == "missing":
            pass
        elif invalid == "symlink":
            sidecar.symlink_to(request_path)
        elif invalid == "fifo":
            os.mkfifo(sidecar)
        elif invalid in {"json", "oversized"}:
            sidecar.write_text("{" if invalid == "json" else " " * 4097)
        else:
            if invalid == "score":
                payload["overall_score"] = 999
            elif invalid == "stale":
                payload["request_sha256"] = "0" * 64
            elif invalid == "destination":
                (cwd.parent / "diagnostics").symlink_to(tmp_path, target_is_directory=True)
            sidecar.write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command, 2)

    report = _runner(tmp_path, fixture, executor=executor).run().to_dict()
    assert len(calls) == 3
    for run in report["cases"][0]["runs"]:
        assert run["error_code"] == "process_nonzero_exit"
        assert run["ready"] is False and run["overall_score"] is None
        assert not (tmp_path / "trial" / run["attempt"] / "diagnostics/subject-failure.json").exists()


def _fixture(
    root: Path,
    *,
    lunar_scores: tuple[tuple[float, float | None], ...] = ((1.0, 0.79), (1.0, 0.81), (0.0, 9.0)),
    baseline_scores: tuple[tuple[float, float | None], ...] = ((1.0, 0.80), (1.0, 0.75), (0.0, 9.0)),
    subject_extra: str = "",
    harness_mutation: str = "",
) -> tuple[Path, Path, Path, tuple[str, ...], tuple[str, ...]]:
    case_root = root / "case"
    (case_root / "data").mkdir(parents=True)
    instruction = case_root / "instruction.md"
    data = case_root / "data" / "items.csv"
    instruction.write_text("Optimize the fixture.\n", encoding="utf-8")
    data.write_text("id\n1\n", encoding="utf-8")
    case = {
        "key": "fixture_case",
        "revision_id": "case-revision-fixture-v1",
        "digest": OBJECT_B,
        "entrypoint": "instruction.md",
        "public_files": [
            {"path": "instruction.md", "size": instruction.stat().st_size, "sha256": _sha(instruction)},
            {"path": "data/items.csv", "size": data.stat().st_size, "sha256": _sha(data)},
        ],
        "harness": {"extractor_sha256": HEX_B, "evaluator_sha256": HEX_C},
    }
    benchmark = {
        "name": "famou-bench",
        "release_version": "1.10.6",
        "publication_digest": OBJECT_A,
    }
    profile = {"name": "famou-agentco-default", "revision": 1, "digest": OBJECT_B}
    suite = root / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "benchmark": benchmark,
                "evaluation_profile": profile,
                "cases": [case],
            }
        ),
        encoding="utf-8",
    )
    baseline = root / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "source": "fm-eval",
                "experiment_id": "fmexp-fixture",
                "authority": "descriptive",
                "conclusion_eligibility": "ineligible",
                "benchmark": benchmark,
                "evaluation_profile": profile,
                "model": {
                    "requested": "gpt-5.6-sol",
                    "effective": "openai/gpt-5.6-sol",
                    "evidence": "not_observable",
                },
                "cases": [
                    {
                        "key": case["key"],
                        "revision_id": case["revision_id"],
                        "digest": case["digest"],
                        "harness": case["harness"],
                        "runs": [
                            {
                                "run_index": index,
                                "ready": True,
                                "extraction_status": "completed",
                                "validity_score": validity,
                                "overall_score": score,
                            }
                            for index, (validity, score) in enumerate(baseline_scores, 1)
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subject = root / "subject.py"
    subject.write_text(
        "import json, pathlib, sys\n"
        "p = pathlib.Path(sys.argv[-1]); q = json.loads(p.read_text())\n"
        "assert q['mode'] == 'normal'\n"
        "assert 'baseline' not in json.dumps(q).lower()\n"
        "assert 'harness' not in json.dumps(q).lower()\n"
        "assert (p.parent / 'case' / q['entrypoint']).is_file()\n"
        "r = {'schema_version':'1','mode':'normal','status':'completed',"
        "'requested_model':q['requested_model'],'effective_model':'openai/gpt-5.6-sol',"
        "'model_evidence':'runtime_observed','interaction_turns':12,"
        "'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120}}\n"
        f"{subject_extra}\n"
        "(p.parent / q['receipt_path']).write_text(json.dumps(r))\n",
        encoding="utf-8",
    )
    harness = root / "harness.py"
    harness.write_text(
        "import json, pathlib, sys\n"
        "p = pathlib.Path(sys.argv[-1]); q = json.loads(p.read_text())\n"
        f"scores = {lunar_scores!r}\n"
        "validity, score = scores[q['run_index'] - 1]\n"
        "r = {'schema_version':'1','status':'completed','benchmark':q['benchmark'],"
        "'evaluation_profile':q['evaluation_profile'],'case':q['case'],'harness':q['harness'],"
        "'extraction_status':'completed','validity_score':validity,'overall_score':score,"
        "'quality_score':score,'detail_metrics':{}}\n"
        f"{harness_mutation}\n"
        "(p.parent / q['receipt_path']).write_text(json.dumps(r))\n",
        encoding="utf-8",
    )
    return (
        suite,
        baseline,
        case_root,
        (str(Path(sys.executable).resolve()), str(subject)),
        (str(Path(sys.executable).resolve()), str(harness)),
    )


def _runner(root: Path, fixture, *, resume: bool = False, executor=None) -> EffectTrialRunner:
    suite, baseline, case_root, subject, harness = fixture
    return EffectTrialRunner(
        suite,
        baseline,
        root / "trial",
        case_sources={"fixture_case": case_root},
        config=EffectTrialConfig(
            runs_per_case=3,
            timeout_seconds=10,
            requested_model="gpt-5.6-sol",
            subject_command=subject,
            harness_command=harness,
        ),
        resume=resume,
        process_executor=executor,
    )


def test_trial_derives_historical_best_and_marks_strict_breakthrough(tmp_path: Path) -> None:
    report = _runner(tmp_path, _fixture(tmp_path)).run()

    case = report.to_dict()["cases"][0]
    assert case["ready_runs"] == 3
    assert case["valid_runs"] == 2
    assert case["valid_rate"] == pytest.approx(2 / 3)
    assert case["lunar_best"] == 0.81
    assert case["webagent_historical_best"] == 0.80
    assert case["score_delta"] == pytest.approx(0.01)
    assert case["score_breakthrough"] is True
    assert case["milestone_achieved"] is True
    assert report.to_dict()["milestone"] == {"achieved": True, "case_keys": ["fixture_case"]}
    assert report.to_dict()["comparability"]["formal_conclusion_eligibility"] == "ineligible"
    assert report.to_dict()["comparability"]["baseline_conclusion_eligibility"] == "ineligible"
    assert "normal_mode_does_not_measure_deep_evolution" in report.to_dict()["comparability"]["limitations"]
    assert "process_capability_separation_is_not_an_os_sandbox" in report.to_dict()["comparability"]["limitations"]

    subject_roots = sorted((tmp_path / "trial" / "cases" / "fixture_case" / "runs").glob("*/attempts/*/subject"))
    assert len(subject_roots) == 3 and len({item.resolve() for item in subject_roots}) == 3
    for subject_root in subject_roots:
        assert not (subject_root / "gt.json").exists()
        assert not (subject_root / "tests").exists()
        request = json.loads((subject_root / "request.json").read_text(encoding="utf-8"))
        assert "baseline" not in json.dumps(request).lower()
        assert "harness" not in json.dumps(request).lower()

    persisted = (tmp_path / "trial" / "report.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in persisted
    assert _fixture.__name__ not in persisted


def test_trial_accepts_company_platform_baseline_without_webagent_alias(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["source"] = "company-platform"
    payload["provenance"] = {"source": "company-platform", "adapter": "company-platform"}
    baseline.write_text(json.dumps(payload), encoding="utf-8")

    report = _runner(tmp_path, (suite, baseline, case_root, subject, harness)).run().to_dict()
    case = report["cases"][0]
    assert case["baseline_historical_best"] == 0.80
    assert "webagent_historical_best" not in case
    assert report["baseline"]["source"] == "company-platform"
    assert report["baseline"]["provenance"] == {
        "source": "company-platform",
        "adapter": "company-platform",
    }
    assert report["comparability"]["baseline_source"] == "company-platform"
    assert report["comparability"]["baseline_adapter"] == "company-platform"


def test_equal_or_invalid_scores_do_not_achieve_milestone(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        lunar_scores=((1.0, 0.80), (0.0, 9.0), (1.0, 0.79)),
    )
    case = _runner(tmp_path, fixture).run().to_dict()["cases"][0]
    assert case["lunar_best"] == 0.80
    assert case["score_delta"] == 0.0
    assert case["score_breakthrough"] is False
    assert case["milestone_achieved"] is False


def test_trial_accepts_two_cases_and_keeps_model_mismatch_descriptive(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    second_root = tmp_path / "case-two"
    (second_root / "data").mkdir(parents=True)
    for relative in ("instruction.md", "data/items.csv"):
        second_root.joinpath(relative).write_bytes(case_root.joinpath(relative).read_bytes())
    suite_payload = json.loads(suite.read_text(encoding="utf-8"))
    second_case = json.loads(json.dumps(suite_payload["cases"][0]))
    second_case.update({"key": "fixture_case_two", "revision_id": "case-revision-fixture-v2"})
    suite_payload["cases"].append(second_case)
    suite.write_text(json.dumps(suite_payload), encoding="utf-8")
    baseline_payload = json.loads(baseline.read_text(encoding="utf-8"))
    second_baseline = json.loads(json.dumps(baseline_payload["cases"][0]))
    second_baseline.update({"key": "fixture_case_two", "revision_id": "case-revision-fixture-v2"})
    baseline_payload["cases"].append(second_baseline)
    baseline.write_text(json.dumps(baseline_payload), encoding="utf-8")

    report = EffectTrialRunner(
        suite,
        baseline,
        tmp_path / "two-case-trial",
        case_sources={"fixture_case": case_root, "fixture_case_two": second_root},
        config=EffectTrialConfig(
            runs_per_case=3,
            timeout_seconds=10,
            requested_model="gpt-5.6-sol",
            subject_command=subject,
            harness_command=harness,
        ),
    ).run().to_dict()
    assert [case["key"] for case in report["cases"]] == ["fixture_case", "fixture_case_two"]
    assert report["milestone"]["case_keys"] == ["fixture_case", "fixture_case_two"]
    assert report["baseline"]["experiment_id"] == "fmexp-fixture"
    assert report["cases"][0]["harness"]["evaluator_sha256"] == HEX_C

    mismatch = _fixture(
        tmp_path / "model-mismatch",
        subject_extra="r['effective_model'] = 'openai/different-model'",
    )
    case = _runner(tmp_path / "model-mismatch", mismatch).run().to_dict()["cases"][0]
    assert case["score_breakthrough"] is True
    assert case["model_identity_match"] is False
    assert case["milestone_achieved"] is False


def test_suite_rejects_private_paths_symlinks_and_changed_public_bytes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    suite, baseline, case_root, subject, harness = fixture
    payload = json.loads(suite.read_text(encoding="utf-8"))
    payload["cases"][0]["public_files"].append({"path": "gt.json", "size": 2, "sha256": HEX_A})
    suite.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="private"):
        _runner(tmp_path, (suite, baseline, case_root, subject, harness))

    clean = _fixture(tmp_path / "changed")
    clean[2].joinpath("instruction.md").write_text("changed", encoding="utf-8")
    with pytest.raises(EffectTrialError, match="digest"):
        _runner(tmp_path / "changed", clean)

    linked = _fixture(tmp_path / "linked")
    original = linked[2] / "data" / "items.csv"
    elsewhere = tmp_path / "elsewhere.csv"
    elsewhere.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    original.unlink()
    original.symlink_to(elsewhere)
    with pytest.raises(EffectTrialError, match="symlink"):
        _runner(tmp_path / "linked", linked)


def test_subject_score_injection_and_harness_identity_mismatch_fail_closed(tmp_path: Path) -> None:
    injected = _fixture(tmp_path / "injected", subject_extra="r['overall_score'] = 999")
    report = _runner(tmp_path / "injected", injected).run().to_dict()
    assert report["cases"][0]["ready_runs"] == 0
    assert report["cases"][0]["milestone_achieved"] is False
    assert {item["error_code"] for item in report["cases"][0]["runs"]} == {"subject_receipt_invalid"}

    mismatched = _fixture(
        tmp_path / "mismatch",
        harness_mutation="r['harness']['evaluator_sha256'] = 'd' * 64",
    )
    report = _runner(tmp_path / "mismatch", mismatched).run().to_dict()
    assert report["cases"][0]["ready_runs"] == 0
    assert {item["error_code"] for item in report["cases"][0]["runs"]} == {"harness_receipt_invalid"}

    preseeded = _fixture(
        tmp_path / "preseeded",
        subject_extra="(p.parent.parent / 'harness').mkdir(); (p.parent.parent / 'harness' / 'receipt.json').write_text('{}')",
    )
    report = _runner(tmp_path / "preseeded", preseeded).run().to_dict()
    assert report["cases"][0]["ready_runs"] == 0
    assert {item["error_code"] for item in report["cases"][0]["runs"]} == {"subject_created_harness_workspace"}


def test_interrupted_trial_resumes_only_unfinished_runs_and_rejects_record_drift(tmp_path: Path) -> None:
    calls = 0

    def interrupt_second_subject(command, *, cwd, env, timeout):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return subprocess.run(command, cwd=cwd, env=env, timeout=timeout, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    fixture = _fixture(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        _runner(tmp_path, fixture, executor=interrupt_second_subject).run()
    first_record = tmp_path / "trial" / "cases" / "fixture_case" / "runs" / "001" / "record.json"
    assert first_record.is_file()

    resumed_calls = 0

    def count_resume(command, *, cwd, env, timeout):
        nonlocal resumed_calls
        resumed_calls += 1
        return subprocess.run(command, cwd=cwd, env=env, timeout=timeout, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    report = _runner(tmp_path, fixture, resume=True, executor=count_resume).run()
    assert report.to_dict()["cases"][0]["ready_runs"] == 3
    assert resumed_calls == 4  # subject + harness for only logical runs 2 and 3
    assert (tmp_path / "trial" / "cases" / "fixture_case" / "runs" / "002" / "attempts" / "002").is_dir()

    payload = json.loads(first_record.read_text(encoding="utf-8"))
    payload["overall_score"] = 100
    first_record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="record digest"):
        _runner(tmp_path, fixture, resume=True).run()


def test_unregistered_future_run_record_is_rescored(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls = 0

    def preseed_future_record(command, *, cwd, env, timeout):
        nonlocal calls
        calls += 1
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if cwd.name == "subject":
            request = json.loads(Path(command[-1]).read_text())
            if request["run_index"] == 1:
                forged = tmp_path / "trial" / "cases" / "fixture_case" / "runs" / "002"
                forged.joinpath("attempts", "001").mkdir(parents=True)
                forged.joinpath("record.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "1",
                            "case_key": "fixture_case",
                            "run_index": 2,
                            "attempt": "cases/fixture_case/runs/002/attempts/001",
                            "status": "completed",
                            "ready": True,
                            "elapsed_ms": 1,
                            "requested_model": "gpt-5.6-sol",
                            "effective_model": "openai/gpt-5.6-sol",
                            "model_evidence": "runtime_observed",
                            "interaction_turns": 1,
                            "usage": None,
                            "extraction_status": "completed",
                            "validity_score": 1.0,
                            "overall_score": 0.99,
                            "quality_score": 0.99,
                            "detail_metrics": {},
                            "error_code": None,
                        }
                    ),
                    encoding="utf-8",
                )
        return result

    report = _runner(tmp_path, fixture, executor=preseed_future_record).run().to_dict()

    run_two = report["cases"][0]["runs"][1]
    assert calls == 6
    assert run_two["overall_score"] == 0.81
    assert run_two["attempt"].endswith("/002")


def test_resume_rejects_a_record_missing_from_frozen_state(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _runner(tmp_path, fixture).run()
    record = tmp_path / "trial" / "cases" / "fixture_case" / "runs" / "002" / "record.json"
    record.unlink()
    with pytest.raises(EffectTrialError, match="missing despite frozen state"):
        _runner(tmp_path, fixture, resume=True).run()


def test_baseline_requires_per_run_receipts_not_a_manual_best(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    baseline = fixture[1]
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["cases"][0]["best_score"] = 0.80
    with pytest.raises(EffectTrialError, match="unsupported"):
        baseline.write_text(json.dumps(payload), encoding="utf-8")
        _runner(tmp_path, fixture)


def test_trial_rejects_out_of_range_validity(tmp_path: Path) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["cases"][0]["runs"][0]["validity_score"] = 2.0
    baseline.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="between zero and one"):
        _runner(tmp_path, (suite, baseline, case_root, subject, harness))


def test_effect_trial_cli_is_standalone_json_and_keeps_env_values_out_of_report(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    monkeypatch.setenv("LUNAR_SUBJECT_SECRET", "subject-secret-value")
    monkeypatch.setenv("LUNAR_HARNESS_SECRET", "harness-secret-value")
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "effect-trial",
            str(suite),
            str(baseline),
            "--case-source",
            f"fixture_case={case_root}",
            "--subject-command",
            " ".join(subject),
            "--harness-command",
            " ".join(harness),
            "--requested-model",
            "gpt-5.6-sol",
            "--runs-per-case",
            "3",
            "--timeout",
            "10",
            "--subject-env",
            "LUNAR_SUBJECT_SECRET",
            "--harness-env",
            "LUNAR_HARNESS_SECRET",
            "--workspace",
            str(tmp_path / "cli-trial"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["milestone"]["achieved"] is True
    persisted = (tmp_path / "cli-trial" / "report.json").read_text(encoding="utf-8")
    assert "subject-secret-value" not in persisted
    assert "harness-secret-value" not in persisted
    assert str(subject[1]) not in persisted
    assert not (tmp_path / ".famou").exists()


def test_effect_trial_cli_rejects_missing_env_and_malformed_case_source(
    tmp_path: Path, capsys
) -> None:
    suite, baseline, case_root, subject, harness = _fixture(tmp_path)
    base = [
        "effect-trial",
        str(suite),
        str(baseline),
        "--subject-command",
        " ".join(subject),
        "--harness-command",
        " ".join(harness),
        "--requested-model",
        "gpt-5.6-sol",
        "--workspace",
        str(tmp_path / "bad-trial"),
        "--json",
    ]
    assert main([*base, "--case-source", str(case_root)]) == 2
    assert "KEY=PATH" in json.loads(capsys.readouterr().err)["error"]

    assert main([*base, "--case-source", f"fixture_case={case_root}", "--subject-env", "MISSING_EFFECT_ENV_048"]) == 2
    assert "not set" in json.loads(capsys.readouterr().err)["error"]


def test_resume_rejects_changed_command_file_identity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _runner(tmp_path, fixture).run()
    Path(fixture[3][1]).write_text("raise SystemExit(99)\n", encoding="utf-8")
    with pytest.raises(EffectTrialError, match="frozen trial identity"):
        _runner(tmp_path, fixture, resume=True).run()


def test_resume_accepts_legacy_no_profile_state_identity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    runner = _runner(tmp_path, fixture)
    runner.run()
    state_path = tmp_path / "trial" / "control" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["identity"]["config"].pop("model_profile_sha256")
    state_path.write_text(json.dumps(state), encoding="utf-8")

    resumed = _runner(tmp_path, fixture, resume=True).run().to_dict()
    assert resumed["cases"][0]["ready_runs"] == 3


def test_subject_command_cannot_override_injected_model_profile(tmp_path: Path) -> None:
    profile = ModelProfile("fixture-profile", "gpt-5.6-sol")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")
    fixture = _fixture(tmp_path)
    _suite, _baseline, _case_root, subject, harness = fixture
    with pytest.raises(EffectTrialError, match="must not provide --model-profile"):
        EffectTrialConfig(
            requested_model="gpt-5.6-sol",
            subject_command=(*subject, "--model-profile", str(profile_path)),
            harness_command=harness,
            subject_model_profile_path=profile_path,
        )


def test_profile_cost_telemetry_uses_cost_bound_not_token_bound(tmp_path: Path) -> None:
    profile = ModelProfile(
        "fixture-profile",
        "gpt-5.6-sol",
        input_cost_per_1k_micros=1_000_000_000_000,
        output_cost_per_1k_micros=1_000_000_000_000,
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")
    digest = _model_profile_digest(profile)
    fixture = _fixture(
        tmp_path,
        subject_extra=f"r['model_profile_sha256']={digest!r}; r['cost_micros']={MAX_TOKENS + 1}",
    )
    suite, baseline, case_root, subject, harness = fixture
    config = EffectTrialConfig(
        runs_per_case=3,
        timeout_seconds=10,
        requested_model="gpt-5.6-sol",
        subject_command=subject,
        harness_command=harness,
        subject_model_profile_path=profile_path,
    )
    report = EffectTrialRunner(
        suite,
        baseline,
        tmp_path / "cost-trial",
        case_sources={"fixture_case": case_root},
        config=config,
    ).run().to_dict()
    assert report["cases"][0]["runs"][0]["cost_micros"] == MAX_TOKENS + 1
    assert MAX_COST_MICROS > MAX_TOKENS


def test_model_profile_provenance_is_bound_to_request_receipt_and_resume(tmp_path: Path) -> None:
    profile = ModelProfile(
        "fixture-profile",
        "gpt-5.6-sol",
        max_steps=8,
        max_total_tokens=1000,
        input_cost_per_1k_micros=100,
        output_cost_per_1k_micros=200,
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")
    digest = _model_profile_digest(profile)
    fixture = _fixture(
        tmp_path,
        subject_extra=f"r['model_profile_sha256']={digest!r}; r['cost_micros']=7",
    )
    suite, baseline, case_root, subject, harness = fixture
    config = EffectTrialConfig(
        runs_per_case=3,
        timeout_seconds=10,
        requested_model="gpt-5.6-sol",
        subject_command=subject,
        harness_command=harness,
        model_profile_sha256=digest,
        subject_model_profile_path=profile_path,
    )
    report = EffectTrialRunner(
        suite,
        baseline,
        tmp_path / "profiled-trial",
        case_sources={"fixture_case": case_root},
        config=config,
    ).run().to_dict()
    run = report["cases"][0]["runs"][0]
    assert run["model_profile_sha256"] == digest
    assert run["cost_micros"] == 7
    request = json.loads(
        (tmp_path / "profiled-trial" / "cases" / "fixture_case" / "runs" / "001" / "attempts" / "001" / "subject" / "request.json").read_text()
    )
    assert request["model_profile_sha256"] == digest

    changed = profile.to_dict()
    changed["max_steps"] = 9
    profile_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="model profile file changed"):
        EffectTrialRunner(
            suite,
            baseline,
            tmp_path / "profiled-trial",
            case_sources={"fixture_case": case_root},
            config=config,
            resume=True,
        ).run()


def test_baseline_provenance_must_match_source_and_allowlisted_adapter(tmp_path: Path) -> None:
    _, baseline_path, _, _, _ = _fixture(tmp_path)
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["provenance"] = {"source": "other-source", "adapter": "company-platform"}
    with pytest.raises(EffectTrialError, match="provenance source must match"):
        TrialBaseline.from_dict(payload)

    payload["provenance"] = {"source": "fm-eval", "adapter": "untrusted-adapter"}
    with pytest.raises(EffectTrialError, match="provenance adapter is unsupported"):
        TrialBaseline.from_dict(payload)
