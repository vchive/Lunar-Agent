import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from famou.cli import main
from famou.effect_trial import EffectTrialConfig, EffectTrialError, EffectTrialRunner

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
OBJECT_A = f"sha256:{HEX_A}"
OBJECT_B = f"sha256:{HEX_B}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
