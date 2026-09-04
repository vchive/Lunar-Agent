import hashlib
import json
import stat
import sys
from pathlib import Path

import pytest

from famou.deep_effect_trial import DeepEffectTrialConfig, DeepEffectTrialRunner
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


def _make_command_script(path: Path, source: str) -> tuple[str, ...]:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return (str(Path(sys.executable).resolve()), str(path))


def test_deep_trial_scores_every_round_and_reports_curve(tmp_path: Path) -> None:
    public, suite = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline = {
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
    }
    baseline_path = _write_json(tmp_path / "baseline.json", baseline)
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
    config = DeepEffectTrialConfig(
        base=EffectTrialConfig(
            runs_per_case=1,
            timeout_seconds=10,
            requested_model="model",
            subject_command=subject_script,
            harness_command=harness_script,
        ),
        outer_rounds=5,
    )
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
    assert case["runs"][0]["rounds"][1]["overall_score"] == 0.55

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
