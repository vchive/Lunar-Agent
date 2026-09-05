import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import famou.effect_trial as effect_trial_module
from famou.deep_effect_trial import (
    DeepEffectTrialConfig,
    DeepEffectTrialRunner,
    _failure_statistics,
)
from famou.effect_adapters import EffectAdapterError, famou_case_content_digest, run_subject_adapter
from famou.effect_trial import EffectTrialConfig, EffectTrialError
from famou.runtime import ModelTurn, ToolCall


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class DeepSubjectModel:
    model = "gpt-5.6-sol"
    api_key = "secret-not-persisted"

    def complete(self, messages, tools=(), timeout=None):
        del tools, timeout
        prompt = next(message["content"] for message in reversed(messages) if message["role"] == "user")
        round_index = int(prompt.split("round ", 1)[1].split("/", 1)[0])
        if any(message["role"] == "tool" for message in messages):
            return ModelTurn("done", response_model="openai/gpt-5.6-sol")
        return ModelTurn(
            "round complete",
            (
                ToolCall(
                    f"write-{round_index}",
                    "write_file",
                    {"path": "round.txt", "content": str(round_index)},
                ),
            ),
            response_model="openai/gpt-5.6-sol",
            usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def _deep_subject_request(root: Path, *, round_index: int = 1, previous=None) -> Path:
    (root / "case" / "data").mkdir(parents=True)
    (root / "case" / "instruction.md").write_text("improve the solution", encoding="utf-8")
    (root / "case" / "data" / "instance.json").write_text("{}", encoding="utf-8")
    instruction = root / "case" / "instruction.md"
    data = root / "case" / "data" / "instance.json"
    return _write_json(
        root / f"request-{round_index:03d}.json",
        {
            "schema_version": "1",
            "mode": "deep_evolution",
            "benchmark": {
                "name": "famou-bench",
                "release_version": "content-test",
                "publication_digest": "sha256:" + "1" * 64,
            },
            "case": {"key": "case-a", "revision_id": "rev-a", "digest": "sha256:" + "3" * 64},
            "run_index": 1,
            "round_index": round_index,
            "outer_rounds": 5,
            "requested_model": "gpt-5.6-sol",
            "entrypoint": "instruction.md",
            "public_files": [
                {
                    "path": "instruction.md",
                    "size": instruction.stat().st_size,
                    "sha256": hashlib.sha256(instruction.read_bytes()).hexdigest(),
                },
                {
                    "path": "data/instance.json",
                    "size": data.stat().st_size,
                    "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                },
            ],
            "previous_evaluation": previous,
            "receipt_path": f"receipts/{round_index:03d}.json",
        },
    )


def test_deep_subject_receipt_is_score_free_and_round_scoped(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    request = _deep_subject_request(root)
    request = request.rename(root / "request.json")

    receipt = run_subject_adapter(request, model_runtime=DeepSubjectModel(), max_steps=2)

    assert receipt["mode"] == "deep_evolution"
    assert receipt["round_index"] == 1
    assert receipt["outer_rounds"] == 5
    assert "overall_score" not in receipt
    assert json.loads((root / "receipts" / "001.json").read_text()) == receipt


def test_deep_subject_receipt_binds_to_request_digest(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    request = _deep_subject_request(root)
    request = request.rename(root / "request.json")

    receipt = run_subject_adapter(request, model_runtime=DeepSubjectModel(), max_steps=2)

    assert receipt["request_sha256"] == hashlib.sha256(request.read_bytes()).hexdigest()


def test_deep_subject_requires_adjacent_bounded_feedback(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    request = _deep_subject_request(root, round_index=2)
    request = request.rename(root / "request.json")
    with pytest.raises(EffectAdapterError, match="previous evaluation"):
        run_subject_adapter(request, model_runtime=DeepSubjectModel(), max_steps=2)


def _make_case(tmp_path: Path) -> tuple[Path, dict]:
    public = tmp_path / "public"
    private = tmp_path / "private"
    (public / "data").mkdir(parents=True)
    (private / "data").mkdir(parents=True)
    (private / "tests").mkdir(parents=True)
    (public / "instruction.md").write_text("write solution", encoding="utf-8")
    (public / "data" / "instance.json").write_text("{}", encoding="utf-8")
    (private / "instruction.md").write_bytes((public / "instruction.md").read_bytes())
    (private / "data" / "instance.json").write_bytes((public / "data" / "instance.json").read_bytes())
    (private / "tests" / "extractor_agent.py").write_text("# extractor\n", encoding="utf-8")
    (private / "tests" / "evaluator.py").write_text("# evaluator\n", encoding="utf-8")

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    suite = {
        "schema_version": "1",
        "benchmark": {
            "name": "famou-bench",
            "release_version": "content-test",
            "publication_digest": "sha256:" + "1" * 64,
        },
        "evaluation_profile": {
            "name": "famou-agentco-default",
            "revision": 1,
            "digest": "sha256:" + "2" * 64,
        },
        "cases": [
            {
                "key": "case-a",
                "revision_id": "rev-a",
                "digest": famou_case_content_digest(private),
                "entrypoint": "instruction.md",
                "public_files": [
                    {"path": "instruction.md", "size": 14, "sha256": sha(public / "instruction.md")},
                    {"path": "data/instance.json", "size": 2, "sha256": sha(public / "data" / "instance.json")},
                ],
                "harness": {
                    "extractor_sha256": sha(private / "tests" / "extractor_agent.py"),
                    "evaluator_sha256": sha(private / "tests" / "evaluator.py"),
                },
            }
        ],
    }
    return public, suite


def _write_baseline(tmp_path: Path, suite: dict) -> Path:
    return _write_json(
        tmp_path / "baseline.json",
        {
            "schema_version": "1",
            "source": "fm-eval",
            "experiment_id": "exp",
            "authority": "descriptive",
            "conclusion_eligibility": "ineligible",
            "benchmark": suite["benchmark"],
            "evaluation_profile": suite["evaluation_profile"],
            "model": {"requested": "model", "effective": "model", "evidence": "not_observable"},
            "cases": [
                {
                    "key": "case-a",
                    "revision_id": "rev-a",
                    "digest": suite["cases"][0]["digest"],
                    "harness": suite["cases"][0]["harness"],
                    "runs": [
                        {
                            "run_index": 1,
                            "ready": True,
                            "extraction_status": "completed",
                            "validity_score": 1.0,
                            "overall_score": 0.5,
                        }
                    ],
                }
            ],
        },
    )


def _deep_config(
    subject_command: tuple[str, ...],
    harness_command: tuple[str, ...],
    *,
    runs_per_case: int = 1,
    outer_rounds: int = 1,
) -> DeepEffectTrialConfig:
    return DeepEffectTrialConfig(
        base=EffectTrialConfig(
            runs_per_case=runs_per_case,
            timeout_seconds=10,
            requested_model="model",
            subject_command=subject_command,
            harness_command=harness_command,
        ),
        outer_rounds=outer_rounds,
    )


def _make_command_script(path: Path, source: str) -> tuple[str, ...]:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return (str(Path(sys.executable).resolve()), str(path))


def _make_bound_subject_script(path: Path) -> tuple[str, ...]:
    return _make_command_script(
        path,
        """import hashlib,json,sys
from pathlib import Path
request_path=Path(sys.argv[1]); r=json.loads(request_path.read_text()); n=int(r['round_index'])
Path('answer.json').write_text(str(n)); Path('round.txt').write_text(str(n))
Path(r['receipt_path']).parent.mkdir(parents=True,exist_ok=True)
Path(r['receipt_path']).write_text(json.dumps({'schema_version':'1','mode':'deep_evolution','status':'completed','requested_model':r['requested_model'],'effective_model':'model','model_evidence':'runtime_observed','interaction_turns':1,'usage':None,'round_index':n,'outer_rounds':r['outer_rounds'],'request_sha256':hashlib.sha256(request_path.read_bytes()).hexdigest()}))
""",
    )


def _make_constant_harness_script(path: Path) -> tuple[str, ...]:
    return _make_command_script(
        path,
        """import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text())
Path(r['receipt_path']).write_text(json.dumps({'schema_version':'1','status':'completed','benchmark':r['benchmark'],'evaluation_profile':r['evaluation_profile'],'case':r['case'],'harness':r['harness'],'extraction_status':'completed','validity_score':1.0,'overall_score':0.5,'quality_score':0.5,'detail_metrics':{'objective':1.0}}))
""",
    )


def test_deep_trial_scores_every_round_and_reports_curve(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_command_script(
        tmp_path / "subject.py",
        """import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text()); n=int(r['round_index'])
Path('round.txt').write_text(str(n))
Path(r['receipt_path']).parent.mkdir(parents=True,exist_ok=True)
Path(r['receipt_path']).write_text(json.dumps({'schema_version':'1','mode':'deep_evolution','status':'completed','requested_model':r['requested_model'],'effective_model':'model','model_evidence':'runtime_observed','interaction_turns':1,'usage':None,'round_index':n,'outer_rounds':r['outer_rounds']}))
""",
    )
    harness_script = _make_command_script(
        tmp_path / "harness.py",
        """import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text()); n=int(Path(r['candidate_workspace']).joinpath('round.txt').read_text())
scores=[0.40,0.55,0.55,0.60,0.58]; s=scores[n-1]
Path(r['receipt_path']).write_text(json.dumps({'schema_version':'1','status':'completed','benchmark':r['benchmark'],'evaluation_profile':r['evaluation_profile'],'case':r['case'],'harness':r['harness'],'extraction_status':'completed','validity_score':1.0,'overall_score':s,'quality_score':s,'detail_metrics':{}}))
""",
    )
    config = _deep_config(subject_script, harness_script, runs_per_case=2, outer_rounds=5)
    report = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
    ).run().to_dict()

    case = report["cases"][0]
    assert report["mode"] == "deep_evolution"
    assert report["outer_rounds"] == 5
    assert case["lunar_best"] == 0.60
    assert case["score_delta"] == pytest.approx(0.10)
    assert case["round_curve"][0]["best"] == 0.40
    assert case["round_curve"][3]["best"] == 0.60
    assert case["score_p50"] == pytest.approx(0.60)
    assert case["score_p90"] == pytest.approx(0.60)
    assert case["ready_runs"] == 2
    assert case["round_curve"][0]["evaluated_runs"] == 2
    assert case["round_curve"][3]["score_p90"] == pytest.approx(0.60)
    assert case["runs"][0]["rounds"][1]["overall_score"] == 0.55
    assert case["runs"][0]["rounds"][0]["feedback"]["directive"] == "refine_best"
    assert case["runs"][0]["rounds"][2]["feedback"]["stagnation"]["consecutive_rounds"] == 1
    assert case["failure_statistics"] == {
        "runs": 2,
        "failed_runs": 0,
        "run_error_codes": {},
        "rounds": 10,
        "completed_rounds": 10,
        "round_failure_categories": {"none": 10},
        "round_error_codes": {},
        "timeout_count": 0,
        "per_round": [
            {
                "round_index": index,
                "recorded": 2,
                "completed": 2,
                "failure_categories": {"none": 2},
            }
            for index in range(1, 6)
        ],
    }

    def no_process(*args, **kwargs):
        raise AssertionError("completed deep trial must not re-invoke a process on resume")

    resumed = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
        resume=True,
        process_executor=no_process,
    ).run().to_dict()
    assert resumed["cases"][0]["lunar_best"] == 0.60

    record_path = tmp_path / "deep" / "cases" / "case-a" / "runs" / "001" / "record.json"
    original_record_bytes = record_path.read_bytes()
    record = json.loads(record_path.read_text())
    record["rounds"][0]["feedback"]["directive"] = "repair_validity"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="digest mismatch"):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            resume=True,
            process_executor=no_process,
        ).run()
    record_path.write_bytes(original_record_bytes)

    attempt = tmp_path / "deep" / report["cases"][0]["runs"][0]["attempt"]
    harness_receipt = attempt / "harness-001" / "receipt.json"
    changed = json.loads(harness_receipt.read_text())
    changed["overall_score"] = 0.10
    harness_receipt.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="disagrees"):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            resume=True,
            process_executor=no_process,
        ).run()


def test_deep_resume_rejects_non_score_receipt_drift(tmp_path: Path) -> None:
    """Every persisted harness field remains bound to the logical round record."""
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script)
    runner = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
    )
    runner.run()
    attempt = tmp_path / "deep" / "cases" / "case-a" / "runs" / "001" / "attempts" / "001"
    receipt_path = attempt / "harness-001" / "receipt.json"
    original_receipt_bytes = receipt_path.read_bytes()

    def no_process(*args, **kwargs):
        raise AssertionError("tampered completed run must fail before process invocation")

    for changed_fields in (
        {"validity_score": 0.75},
        {"quality_score": 0.1},
        {"detail_metrics": {"objective": 2.0}},
        {"extraction_status": "failed", "validity_score": 0.0, "overall_score": 0.0},
    ):
        receipt = json.loads(original_receipt_bytes)
        receipt.update(changed_fields)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with pytest.raises(EffectTrialError, match="disagrees"):
            DeepEffectTrialRunner(
                suite_path,
                baseline_path,
                tmp_path / "deep",
                case_sources={"case-a": public},
                config=config,
                resume=True,
                process_executor=no_process,
            ).run()

    receipt_path.write_bytes(original_receipt_bytes)
    subject_receipt_path = attempt / "subject" / "receipts" / "001.json"
    original_subject_receipt_bytes = subject_receipt_path.read_bytes()
    for changed_fields in (
        {"effective_model": "different-model"},
        {"model_evidence": "provider_observed"},
        {"interaction_turns": 2},
        {"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}},
    ):
        subject_receipt = json.loads(original_subject_receipt_bytes)
        subject_receipt.update(changed_fields)
        subject_receipt_path.write_text(json.dumps(subject_receipt), encoding="utf-8")
        with pytest.raises(EffectTrialError, match="disagrees"):
            DeepEffectTrialRunner(
                suite_path,
                baseline_path,
                tmp_path / "deep",
                case_sources={"case-a": public},
                config=config,
                resume=True,
                process_executor=no_process,
            ).run()

    subject_receipt_path.write_bytes(original_subject_receipt_bytes)
    subject_receipt = json.loads(subject_receipt_path.read_text())
    subject_receipt["request_sha256"] = "0" * 64
    subject_receipt_path.write_text(json.dumps(subject_receipt), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="request digest"):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            resume=True,
            process_executor=no_process,
        ).run()

    subject_receipt_path.write_bytes(original_subject_receipt_bytes)
    harness_request_path = attempt / "harness-001" / "request.json"
    harness_request = json.loads(harness_request_path.read_text())
    harness_request["run_index"] = 2
    harness_request_path.write_text(json.dumps(harness_request), encoding="utf-8")
    with pytest.raises(EffectTrialError, match="harness request"):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            resume=True,
            process_executor=no_process,
        ).run()


def test_deep_resume_rejects_symlinked_attempt_ancestor(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script)
    DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
    ).run()

    run_root = tmp_path / "deep" / "cases" / "case-a" / "runs" / "001"
    attempts = run_root / "attempts"
    copied_attempts = run_root / "copied-attempts"
    shutil.copytree(attempts, copied_attempts)
    shutil.rmtree(attempts)
    attempts.symlink_to(copied_attempts, target_is_directory=True)

    def no_process(*args, **kwargs):
        raise AssertionError("unsafe completed artifacts must fail before process invocation")

    with pytest.raises(EffectTrialError, match="contains a symlink"):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            resume=True,
            process_executor=no_process,
        ).run()


def test_deep_resume_reuses_bound_subject_receipt_and_rescores_round(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script, outer_rounds=2)

    def interrupt_after_second_harness(command, *, cwd, env, timeout):
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
        if cwd.name == "harness-002":
            raise KeyboardInterrupt
        return result

    with pytest.raises(KeyboardInterrupt):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            process_executor=interrupt_after_second_harness,
        ).run()

    resumed_processes: list[str] = []

    def rerun_private_harness(command, *, cwd, env, timeout):
        resumed_processes.append(cwd.name)
        assert cwd.name == "harness-002"
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    report = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
        resume=True,
        process_executor=rerun_private_harness,
    ).run().to_dict()

    assert resumed_processes == ["harness-002"]
    assert report["cases"][0]["ready_runs"] == 1
    assert len(report["cases"][0]["runs"][0]["rounds"]) == 2


def test_deep_resume_recovers_record_state_commit_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script, outer_rounds=2)
    original_atomic_json = effect_trial_module._atomic_json
    record_writes = 0

    def interrupt_after_second_record(path, payload, maximum=effect_trial_module.MAX_MANIFEST_BYTES):
        nonlocal record_writes
        content = original_atomic_json(path, payload, maximum)
        if Path(path).name == "record.json":
            record_writes += 1
            if record_writes == 2:
                raise KeyboardInterrupt
        return content

    monkeypatch.setattr(effect_trial_module, "_atomic_json", interrupt_after_second_record)
    with pytest.raises(KeyboardInterrupt):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
        ).run()
    monkeypatch.setattr(effect_trial_module, "_atomic_json", original_atomic_json)

    run_root = tmp_path / "deep" / "cases" / "case-a" / "runs" / "001"
    assert record_writes == 2
    assert (run_root / "record.previous.json").is_file()
    resumed_processes: list[str] = []

    def rerun_private_harness(command, *, cwd, env, timeout):
        resumed_processes.append(cwd.name)
        assert cwd.name == "harness-002"
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    report = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
        resume=True,
        process_executor=rerun_private_harness,
    ).run().to_dict()

    assert resumed_processes == ["harness-002"]
    assert report["cases"][0]["runs"][0]["ready"] is True
    assert not (run_root / "record.previous.json").exists()


def test_deep_resume_rejects_mismatched_previous_record_journal(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script)
    DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
    ).run()

    run_root = tmp_path / "deep" / "cases" / "case-a" / "runs" / "001"
    record_path = run_root / "record.json"
    original = json.loads(record_path.read_text(encoding="utf-8"))
    changed_record = dict(original)
    changed_record["overall_score"] = 0.75
    _write_json(record_path, changed_record)
    forged_previous = dict(original)
    forged_previous["elapsed_ms"] += 1
    _write_json(run_root / "record.previous.json", forged_previous)

    def no_process(*args, **kwargs):
        raise AssertionError("a mismatched journal must fail before process invocation")

    with pytest.raises(EffectTrialError, match="logical run record digest mismatch"):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            resume=True,
            process_executor=no_process,
        ).run()


def test_deep_resume_rejects_harness_artifacts_without_subject_receipt(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script, outer_rounds=2)

    def interrupt_before_second_subject(command, *, cwd, env, timeout):
        request = json.loads(Path(command[-1]).read_text())
        if cwd.name == "subject" and request.get("round_index") == 2:
            raise KeyboardInterrupt
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    with pytest.raises(KeyboardInterrupt):
        DeepEffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "deep",
            case_sources={"case-a": public},
            config=config,
            process_executor=interrupt_before_second_subject,
        ).run()

    harness_root = (
        tmp_path
        / "deep"
        / "cases"
        / "case-a"
        / "runs"
        / "001"
        / "attempts"
        / "001"
        / "harness-002"
    )
    harness_request = {
        "schema_version": "1",
        "candidate_workspace": "../subject",
        "run_index": 1,
        "benchmark": suite["benchmark"],
        "evaluation_profile": suite["evaluation_profile"],
        "case": {"key": "case-a", "revision_id": "rev-a", "digest": suite["cases"][0]["digest"]},
        "harness": suite["cases"][0]["harness"],
        "receipt_path": "receipt.json",
    }
    _write_json(harness_root / "request.json", harness_request)
    _write_json(
        harness_root / "receipt.json",
        {
            "schema_version": "1",
            "status": "completed",
            "benchmark": suite["benchmark"],
            "evaluation_profile": suite["evaluation_profile"],
            "case": harness_request["case"],
            "harness": suite["cases"][0]["harness"],
            "extraction_status": "completed",
            "validity_score": 1.0,
            "overall_score": 0.99,
            "quality_score": 0.99,
            "detail_metrics": {},
        },
    )

    def no_process(*args, **kwargs):
        raise AssertionError("invalid resume artifacts must fail before process invocation")

    report = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
        resume=True,
        process_executor=no_process,
    ).run().to_dict()

    run = report["cases"][0]["runs"][0]
    assert run["ready"] is False
    assert run["error_code"] == "deep_resume_artifact_order_invalid"
    assert len(run["rounds"]) == 1


def test_deep_unregistered_future_run_record_is_rescored(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    subject_script = _make_bound_subject_script(tmp_path / "subject.py")
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script, runs_per_case=2)
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
        request = json.loads(Path(command[-1]).read_text())
        if cwd.name == "subject" and request["run_index"] == 1:
            future = tmp_path / "deep" / "cases" / "case-a" / "runs" / "002"
            attempt = future / "attempts" / "001"
            subject_receipt = attempt / "subject" / "receipts" / "001.json"
            harness_receipt = attempt / "harness-001" / "receipt.json"
            _write_json(
                subject_receipt,
                {
                    "schema_version": "1",
                    "mode": "deep_evolution",
                    "status": "completed",
                    "requested_model": "model",
                    "effective_model": "model",
                    "model_evidence": "runtime_observed",
                    "interaction_turns": 1,
                    "usage": None,
                    "round_index": 1,
                    "outer_rounds": 1,
                },
            )
            _write_json(
                harness_receipt,
                {
                    "schema_version": "1",
                    "status": "completed",
                    "benchmark": suite["benchmark"],
                    "evaluation_profile": suite["evaluation_profile"],
                    "case": {
                        "key": "case-a",
                        "revision_id": "rev-a",
                        "digest": suite["cases"][0]["digest"],
                    },
                    "harness": suite["cases"][0]["harness"],
                    "extraction_status": "completed",
                    "validity_score": 1.0,
                    "overall_score": 0.99,
                    "quality_score": 0.99,
                    "detail_metrics": {},
                },
            )
            round_record = {
                "round_index": 1,
                "status": "completed",
                "ready": True,
                "subject_receipt": "cases/case-a/runs/002/attempts/001/subject/receipts/001.json",
                "harness_receipt": "cases/case-a/runs/002/attempts/001/harness-001/receipt.json",
                "requested_model": "model",
                "effective_model": "model",
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
            _write_json(
                future / "record.json",
                {
                    "schema_version": "1",
                    "case_key": "case-a",
                    "run_index": 2,
                    "attempt": "cases/case-a/runs/002/attempts/001",
                    "status": "completed",
                    "ready": True,
                    "elapsed_ms": 1,
                    "requested_model": "model",
                    "effective_model": "model",
                    "model_evidence": "runtime_observed",
                    "interaction_turns": 1,
                    "usage": None,
                    "extraction_status": "completed",
                    "validity_score": 1.0,
                    "overall_score": 0.99,
                    "quality_score": 0.99,
                    "detail_metrics": {},
                    "error_code": None,
                    "outer_rounds": 1,
                    "rounds": [round_record],
                },
            )
        return result

    report = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
        process_executor=preseed_future_record,
    ).run().to_dict()

    run_two = report["cases"][0]["runs"][1]
    assert calls == 4
    assert run_two["overall_score"] == 0.5
    assert run_two["attempt"].endswith("/002")


def test_deep_subject_cannot_precreate_harness_workspace(tmp_path: Path) -> None:
    """A subject process must never be able to smuggle a score through the harness path."""
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_baseline(tmp_path, suite)
    harness_identity = json.dumps(suite["cases"][0]["harness"], sort_keys=True)
    subject_script = _make_command_script(
        tmp_path / "forger.py",
        f"""import hashlib,json,sys
from pathlib import Path
request_path=Path(sys.argv[1]); r=json.loads(request_path.read_text())
Path('answer.json').write_text('forged')
Path(r['receipt_path']).parent.mkdir(parents=True,exist_ok=True)
Path(r['receipt_path']).write_text(json.dumps({{'schema_version':'1','mode':'deep_evolution','status':'completed','requested_model':r['requested_model'],'effective_model':'model','model_evidence':'runtime_observed','interaction_turns':1,'usage':None,'round_index':r['round_index'],'outer_rounds':r['outer_rounds'],'request_sha256':hashlib.sha256(request_path.read_bytes()).hexdigest()}}))
if Path.cwd().parent.name == '001':
 h=Path('..')/'harness-001'; h.mkdir()
 (h/'request.json').write_text(json.dumps({{'schema_version':'1','candidate_workspace':'../subject','run_index':1,'benchmark':r['benchmark'],'evaluation_profile':{json.dumps(suite['evaluation_profile'], sort_keys=True)},'case':r['case'],'harness':{harness_identity},'receipt_path':'receipt.json'}}))
 (h/'receipt.json').write_text(json.dumps({{'schema_version':'1','status':'completed','benchmark':r['benchmark'],'evaluation_profile':{json.dumps(suite['evaluation_profile'], sort_keys=True)},'case':r['case'],'harness':{harness_identity},'extraction_status':'completed','validity_score':1.0,'overall_score':0.99,'quality_score':0.99,'detail_metrics':{{}}}}))
""",
    )
    harness_script = _make_constant_harness_script(tmp_path / "harness.py")
    config = _deep_config(subject_script, harness_script)
    report = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
    ).run().to_dict()

    case = report["cases"][0]
    assert case["ready_runs"] == 0
    assert case["runs"][0]["error_code"] == "subject_created_harness_workspace"

    resumed = DeepEffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "deep",
        case_sources={"case-a": public},
        config=config,
        resume=True,
    ).run().to_dict()

    run = resumed["cases"][0]["runs"][0]
    assert run["ready"] is True
    assert run["overall_score"] == 0.5
    assert run["attempt"].endswith("/002")


def test_failure_statistics_count_run_and_round_failures() -> None:
    records = [
        {
            "status": "failed",
            "error_code": "process_timeout",
            "rounds": [],
        },
        {
            "status": "completed",
            "error_code": None,
            "rounds": [
                {
                    "round_index": 1,
                    "status": "completed",
                    "feedback": {"failure_category": "invalid_candidate"},
                    "error_code": None,
                },
                {
                    "round_index": 2,
                    "status": "completed",
                    "feedback": {"failure_category": "none"},
                    "error_code": None,
                },
            ],
        },
    ]

    stats = _failure_statistics(records, 3)

    assert stats["runs"] == 2
    assert stats["failed_runs"] == 1
    assert stats["run_error_codes"] == {"process_timeout": 1}
    assert stats["timeout_count"] == 1
    assert stats["rounds"] == 2
    assert stats["completed_rounds"] == 2
    assert stats["round_failure_categories"] == {"invalid_candidate": 1, "none": 1}
    assert stats["per_round"][0] == {
        "round_index": 1,
        "recorded": 1,
        "completed": 1,
        "failure_categories": {"invalid_candidate": 1},
    }
    assert stats["per_round"][2] == {
        "round_index": 3,
        "recorded": 0,
        "completed": 0,
        "failure_categories": {},
    }
