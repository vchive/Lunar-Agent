import hashlib
import json
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Self

import pytest

from famou.cli import main
from famou.effect_adapters import (
    EffectAdapterError,
    convert_fm_eval_baseline,
    famou_case_content_digest,
    run_harness_adapter,
    run_subject_adapter,
)
from famou.effect_trial import EffectTrialConfig, EffectTrialRunner, TrialBaseline
from famou.runtime import ModelTurn, ToolCall


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_suite(case_source: Path, case_root: Path, *, version: str = "1.10.6") -> dict:
    instruction = case_source / "instruction.md"
    public_data = case_source / "data" / "instance.json"
    extractor = case_root / "tests" / "extractor_agent.py"
    evaluator = case_root / "tests" / "evaluator.py"
    return {
        "schema_version": "1",
        "benchmark": {
            "name": "famou-bench",
            "release_version": version,
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
                "revision_id": "fmcase-rev-a",
                "digest": famou_case_content_digest(case_root),
                "entrypoint": "instruction.md",
                "public_files": [
                    {
                        "path": "instruction.md",
                        "size": instruction.stat().st_size,
                        "sha256": _sha(instruction),
                    },
                    {
                        "path": "data/instance.json",
                        "size": public_data.stat().st_size,
                        "sha256": _sha(public_data),
                    },
                ],
                "harness": {
                    "extractor_sha256": _sha(extractor),
                    "evaluator_sha256": _sha(evaluator),
                },
            }
        ],
    }


def _make_case(tmp_path: Path) -> tuple[Path, Path]:
    public = tmp_path / "public"
    private = tmp_path / "private"
    (public / "data").mkdir(parents=True)
    (private / "data").mkdir(parents=True)
    (private / "tests").mkdir(parents=True)
    (public / "instruction.md").write_text(
        "Read case/data/instance.json and write solution.json with answer=42.", encoding="utf-8"
    )
    (public / "data" / "instance.json").write_text('{"target":42}', encoding="utf-8")
    (private / "data" / "instance.json").write_text('{"target":42}', encoding="utf-8")
    (private / "data" / ".DS_Store").write_bytes(b"ignored metadata")
    (private / "data" / "ignored.pyc").write_bytes(b"ignored cache")
    (private / "data" / "__pycache__").mkdir()
    (private / "data" / "__pycache__" / "ignored.pyc").write_bytes(b"ignored cache")
    (private / "instruction.md").write_bytes((public / "instruction.md").read_bytes())
    (private / "tests" / "extractor_agent.py").write_text(
        """import argparse,json,os
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--evaluator'); p.add_argument('--workspace'); p.add_argument('--output'); a=p.parse_args()
out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
assert os.environ.get('EXTRACTOR_SECRET') == 'extractor-only'
src=Path(a.workspace)/'solution.json'
(out/'solution.json').write_bytes(src.read_bytes())
print(json.dumps({'status':'success','notes':'normalized'}))
""",
        encoding="utf-8",
    )
    (private / "tests" / "evaluator.py").write_text(
        """import argparse,json,os
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--data-dir'); p.add_argument('--submission-dir'); a=p.parse_args()
assert 'EXTRACTOR_SECRET' not in os.environ
assert 'FAMOU_API_KEY' not in os.environ
answer=json.loads((Path(a.submission_dir)/'solution.json').read_text())['answer']
score=0.81 if answer == 42 else 0.0
print(json.dumps({'overall_score':score,'validity_score':float(answer == 42),'quality_score':score,'objective':42}))
""",
        encoding="utf-8",
    )
    return public, private


class SubjectModel:
    model = "gpt-5.6-sol"
    api_key = "do-not-persist"

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, messages, tools=(), timeout=None):
        del messages, tools, timeout
        self.turn += 1
        if self.turn == 1:
            return ModelTurn(
                "",
                (
                    ToolCall(
                        "1",
                        "write_file",
                        {"path": "solution.json", "content": '{"answer":42}'},
                    ),
                    ToolCall(
                        "2",
                        "write_file",
                        {"path": "_agent_summary.md", "content": "Final: solution.json"},
                    ),
                ),
                response_model="openai/gpt-5.6-sol",
                usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            )
        return ModelTurn(
            "done",
            response_model="openai/gpt-5.6-sol",
            usage={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def _subject_request(subject_root: Path) -> Path:
    (subject_root / "case" / "data").mkdir(parents=True)
    (subject_root / "case" / "instruction.md").write_text("write solution.json", encoding="utf-8")
    (subject_root / "case" / "data" / "instance.json").write_text("{}", encoding="utf-8")
    instruction = subject_root / "case" / "instruction.md"
    data = subject_root / "case" / "data" / "instance.json"
    return _write_json(
        subject_root / "request.json",
        {
            "schema_version": "1",
            "mode": "normal",
            "benchmark": {
                "name": "famou-bench",
                "release_version": "1.10.6",
                "publication_digest": "sha256:" + "1" * 64,
            },
            "case": {
                "key": "case-a",
                "revision_id": "fmcase-rev-a",
                "digest": "sha256:" + "3" * 64,
            },
            "run_index": 1,
            "requested_model": "gpt-5.6-sol",
            "entrypoint": "instruction.md",
            "public_files": [
                {
                    "path": "instruction.md",
                    "size": instruction.stat().st_size,
                    "sha256": _sha(instruction),
                },
                {
                    "path": "data/instance.json",
                    "size": data.stat().st_size,
                    "sha256": _sha(data),
                },
            ],
            "receipt_path": "receipt.json",
        },
    )


def test_builtin_subject_runs_fresh_agent_and_writes_score_free_receipt(tmp_path: Path) -> None:
    request = _subject_request(tmp_path / "subject")

    receipt = run_subject_adapter(request, model_runtime=SubjectModel(), max_steps=4)

    assert json.loads((request.parent / "solution.json").read_text()) == {"answer": 42}
    assert receipt == {
        "schema_version": "1",
        "mode": "normal",
        "status": "completed",
        "requested_model": "gpt-5.6-sol",
        "effective_model": "openai/gpt-5.6-sol",
        "model_evidence": "provider_observed",
        "interaction_turns": 2,
        "usage": {"input_tokens": 150, "output_tokens": 30, "total_tokens": 180},
    }
    assert "score" not in json.dumps(receipt)
    assert json.loads((request.parent / "receipt.json").read_text()) == receipt


def test_builtin_subject_rejects_unsafe_or_mismatched_request(tmp_path: Path) -> None:
    request = _subject_request(tmp_path / "subject")
    payload = json.loads(request.read_text())
    payload["receipt_path"] = "../receipt.json"
    _write_json(request, payload)
    with pytest.raises(EffectAdapterError, match="receipt"):
        run_subject_adapter(request, model_runtime=SubjectModel())

    request = _subject_request(tmp_path / "other")
    with pytest.raises(EffectAdapterError, match="model"):
        run_subject_adapter(request, model="different", model_runtime=SubjectModel())


def test_builtin_subject_detects_public_case_mutation(tmp_path: Path) -> None:
    request = _subject_request(tmp_path / "subject")

    class MutatingModel(SubjectModel):
        def complete(self, messages, tools=(), timeout=None):
            del messages, tools, timeout
            self.turn += 1
            if self.turn == 1:
                return ModelTurn(
                    "",
                    (
                        ToolCall(
                            "1",
                            "write_file",
                            {"path": "case/instruction.md", "content": "changed"},
                        ),
                    ),
                )
            return ModelTurn("done")

    with pytest.raises(EffectAdapterError, match="public"):
        run_subject_adapter(request, model_runtime=MutatingModel())


def _harness_request(root: Path, suite: dict) -> Path:
    case = suite["cases"][0]
    return _write_json(
        root / "harness" / "request.json",
        {
            "schema_version": "1",
            "candidate_workspace": "../subject",
            "run_index": 1,
            "benchmark": suite["benchmark"],
            "evaluation_profile": suite["evaluation_profile"],
            "case": {key: case[key] for key in ("key", "revision_id", "digest")},
            "harness": case["harness"],
            "receipt_path": "receipt.json",
        },
    )


def test_builtin_harness_runs_exact_extractor_then_credential_free_evaluator(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite = _make_suite(public, private)
    attempt = tmp_path / "attempt"
    (attempt / "subject" / "case" / "data").mkdir(parents=True)
    (attempt / "subject" / "case" / "instruction.md").write_bytes(
        (public / "instruction.md").read_bytes()
    )
    (attempt / "subject" / "case" / "data" / "instance.json").write_bytes(
        (public / "data" / "instance.json").read_bytes()
    )
    (attempt / "subject" / "solution.json").write_text('{"answer":42}', encoding="utf-8")
    request = _harness_request(attempt, suite)

    receipt = run_harness_adapter(
        request,
        private,
        python_bin=sys.executable,
        extractor_environment={"EXTRACTOR_SECRET": "extractor-only", "FAMOU_API_KEY": "hidden"},
    )

    assert receipt["extraction_status"] == "completed"
    assert receipt["validity_score"] == 1.0
    assert receipt["overall_score"] == 0.81
    assert receipt["quality_score"] == 0.81
    assert receipt["detail_metrics"] == {"objective": 42.0}
    assert receipt["harness"] == suite["cases"][0]["harness"]
    persisted = (request.parent / "receipt.json").read_text()
    assert "extractor-only" not in persisted
    assert str(private) not in persisted


def test_builtin_harness_fails_closed_on_script_drift_and_extractor_failure(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite = _make_suite(public, private)
    attempt = tmp_path / "attempt"
    (attempt / "subject" / "case" / "data").mkdir(parents=True)
    (attempt / "subject" / "case" / "instruction.md").write_bytes(
        (public / "instruction.md").read_bytes()
    )
    (attempt / "subject" / "case" / "data" / "instance.json").write_bytes(
        (public / "data" / "instance.json").read_bytes()
    )
    (attempt / "subject" / "solution.json").write_text('{"answer":42}', encoding="utf-8")
    request = _harness_request(attempt, suite)
    (private / "tests" / "evaluator.py").write_text("# drift", encoding="utf-8")

    with pytest.raises(EffectAdapterError, match="digest"):
        run_harness_adapter(request, private, python_bin=sys.executable)


def test_builtin_harness_partial_extraction_skips_evaluator(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    marker = private / "evaluator-ran"
    (private / "tests" / "extractor_agent.py").write_text(
        "import json\nprint(json.dumps({'status':'partial','notes':'missing rows'}))\n",
        encoding="utf-8",
    )
    (private / "tests" / "evaluator.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        encoding="utf-8",
    )
    suite = _make_suite(public, private)
    attempt = tmp_path / "attempt"
    (attempt / "subject" / "case" / "data").mkdir(parents=True)
    (attempt / "subject" / "case" / "instruction.md").write_bytes(
        (public / "instruction.md").read_bytes()
    )
    (attempt / "subject" / "case" / "data" / "instance.json").write_bytes(
        (public / "data" / "instance.json").read_bytes()
    )
    request = _harness_request(attempt, suite)

    receipt = run_harness_adapter(request, private, python_bin=sys.executable)

    assert receipt["extraction_status"] == "partial"
    assert receipt["validity_score"] == 0.0
    assert not marker.exists()


def _results(experiment_id: str = "fmexp-fixture") -> dict:
    return {
        "experiment": {"id": experiment_id},
        "results": [
            {
                "case": "case-a",
                "run_index": 0,
                "projection_state": "ready",
                "evaluation_status": "scored",
                "extraction_status": "extracted",
                "validity_score": 1.0,
                "overall_score": 0.79,
            },
            {
                "case": "case-a",
                "run_index": 1,
                "projection_state": "ready",
                "evaluation_status": "scored",
                "extraction_status": "extracted",
                "validity_score": 1.0,
                "overall_score": 0.80,
            },
        ],
    }


def test_offline_fm_eval_results_convert_to_strict_per_run_baseline(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(tmp_path / "results.json", _results())
    output = tmp_path / "baseline.json"
    legacy_temporary = tmp_path / ".baseline.json.tmp"
    legacy_temporary.write_text("owner file", encoding="utf-8")

    converted = convert_fm_eval_baseline(
        results_path,
        suite_path,
        output,
        experiment_id="fmexp-fixture",
        requested_model="gpt-5.6-sol",
        effective_model="openai/gpt-5.6-sol",
        model_evidence="not_observable",
    )

    parsed = TrialBaseline.from_dict(converted)
    assert parsed.cases[0].best() == 0.80
    assert [run.run_index for run in parsed.cases[0].runs] == [1, 2]
    assert "best" not in output.read_text()
    assert legacy_temporary.read_text(encoding="utf-8") == "owner file"


def test_offline_converter_rejects_identity_duplicates_and_overwrite(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results = _results("wrong")
    results["results"][1]["run_index"] = 0
    results_path = _write_json(tmp_path / "results.json", results)
    output = tmp_path / "baseline.json"

    with pytest.raises(EffectAdapterError, match="experiment"):
        convert_fm_eval_baseline(
            results_path,
            suite_path,
            output,
            experiment_id="expected",
            requested_model="model",
            effective_model="model",
            model_evidence="not_observable",
        )

    results.pop("experiment")
    _write_json(results_path, results)
    with pytest.raises(EffectAdapterError, match="experiment identity"):
        convert_fm_eval_baseline(
            results_path,
            suite_path,
            output,
            experiment_id="expected",
            requested_model="model",
            effective_model="model",
            model_evidence="not_observable",
        )

    results["experiment"] = {"id": "expected"}
    _write_json(results_path, results)
    with pytest.raises(EffectAdapterError, match="duplicate"):
        convert_fm_eval_baseline(
            results_path,
            suite_path,
            output,
            experiment_id="expected",
            requested_model="model",
            effective_model="model",
            model_evidence="not_observable",
        )

    clean = _results("expected")
    clean["results"] = clean["results"][:1]
    _write_json(results_path, clean)
    output.write_text("owner file", encoding="utf-8")
    with pytest.raises(EffectAdapterError, match="already exists"):
        convert_fm_eval_baseline(
            results_path,
            suite_path,
            output,
            experiment_id="expected",
            requested_model="model",
            effective_model="model",
            model_evidence="not_observable",
        )


def test_effect_baseline_cli_converts_local_results(tmp_path: Path, capsys) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(tmp_path / "results.json", _results())
    output = tmp_path / "baseline.json"

    status = main(
        [
            "effect-baseline",
            str(results_path),
            str(suite_path),
            str(output),
            "--experiment-id",
            "fmexp-fixture",
            "--requested-model",
            "gpt-5.6-sol",
            "--effective-model",
            "openai/gpt-5.6-sol",
            "--model-evidence",
            "not_observable",
            "--json",
        ]
    )

    assert status == 0
    assert json.loads(capsys.readouterr().out)["experiment_id"] == "fmexp-fixture"
    assert TrialBaseline.from_dict(json.loads(output.read_text())).cases[0].best() == 0.80


def test_effect_trial_accepts_nullable_subject_usage(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite = _make_suite(public, private)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    baseline_path = _write_json(
        tmp_path / "baseline.json",
        {
            "schema_version": "1",
            "source": "fm-eval",
            "experiment_id": "fmexp-fixture",
            "authority": "descriptive",
            "conclusion_eligibility": "ineligible",
            "benchmark": suite["benchmark"],
            "evaluation_profile": suite["evaluation_profile"],
            "model": {
                "requested": "gpt-5.6-sol",
                "effective": "gpt-5.6-sol",
                "evidence": "not_observable",
            },
            "cases": [
                {
                    "key": "case-a",
                "revision_id": "fmcase-rev-a",
                "digest": suite["cases"][0]["digest"],
                    "harness": suite["cases"][0]["harness"],
                    "runs": [
                        {
                            "run_index": 1,
                            "ready": True,
                            "extraction_status": "completed",
                            "validity_score": 1.0,
                            "overall_score": 0.80,
                        }
                    ],
                }
            ],
        },
    )
    subject = tmp_path / "subject.py"
    subject.write_text(
        """#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\np=Path(sys.argv[1]); r=json.loads(p.read_text()); (p.parent/'solution.json').write_text('{\"answer\":42}'); (p.parent/r['receipt_path']).write_text(json.dumps({'schema_version':'1','mode':'normal','status':'completed','requested_model':r['requested_model'],'effective_model':'gpt-5.6-sol','model_evidence':'runtime_observed','interaction_turns':1,'usage':None}))\n""",
        encoding="utf-8",
    )
    subject.chmod(subject.stat().st_mode | stat.S_IXUSR)

    report = EffectTrialRunner(
        suite_path,
        baseline_path,
        tmp_path / "trial",
        case_sources={"case-a": public},
        config=EffectTrialConfig(
            runs_per_case=1,
            timeout_seconds=10,
            requested_model="gpt-5.6-sol",
            subject_command=(str(subject),),
            harness_command=(
                str(Path(sys.executable).parent / "lunar-agent"),
                "effect-harness",
                "--case-root",
                str(private),
                "--extractor-env",
                "EXTRACTOR_SECRET",
            ),
            harness_environment={"EXTRACTOR_SECRET": "extractor-only"},
        ),
    ).run().to_dict()

    assert report["cases"][0]["runs"][0]["usage"] is None
    assert report["cases"][0]["lunar_best"] == 0.81


class EffectModelHandler(BaseHTTPRequestHandler):
    requests: ClassVar[int] = 0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests += 1
        has_tool_result = any(item.get("role") == "tool" for item in payload["messages"])
        if has_tool_result:
            message = {"content": "solution ready"}
        else:
            message = {
                "content": "",
                "tool_calls": [
                    {
                        "id": "write-solution",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {"path": "solution.json", "content": '{"answer":42}'}
                            ),
                        },
                    },
                    {
                        "id": "write-summary",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {
                                    "path": "_agent_summary.md",
                                    "content": "Final: solution.json",
                                }
                            ),
                        },
                    },
                ],
            }
        body = json.dumps(
            {
                "model": "openai/gpt-5.6-sol",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                "choices": [{"message": message}],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class EffectModelServer:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), EffectModelHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> Self:
        EffectModelHandler.requests = 0
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_all_builtin_adapters_complete_effect_trial_end_to_end(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite = _make_suite(public, private)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    results_path = _write_json(tmp_path / "results.json", _results())
    baseline_path = tmp_path / "baseline.json"
    convert_fm_eval_baseline(
        results_path,
        suite_path,
        baseline_path,
        experiment_id="fmexp-fixture",
        requested_model="gpt-5.6-sol",
        effective_model="openai/gpt-5.6-sol",
        model_evidence="not_observable",
    )
    lunar = Path(sys.executable).parent / "lunar-agent"

    with EffectModelServer() as server:
        report = EffectTrialRunner(
            suite_path,
            baseline_path,
            tmp_path / "trial-builtin",
            case_sources={"case-a": public},
            config=EffectTrialConfig(
                runs_per_case=1,
                timeout_seconds=10,
                requested_model="gpt-5.6-sol",
                subject_command=(
                    str(lunar),
                    "effect-subject",
                    "--endpoint",
                    server.url,
                    "--model",
                    "gpt-5.6-sol",
                    "--max-steps",
                    "4",
                ),
                harness_command=(
                    str(lunar),
                    "effect-harness",
                    "--case-root",
                    str(private),
                    "--extractor-env",
                    "EXTRACTOR_SECRET",
                ),
                harness_environment={"EXTRACTOR_SECRET": "extractor-only"},
            ),
        ).run().to_dict()

    case = report["cases"][0]
    assert EffectModelHandler.requests == 2
    assert case["lunar_best"] == 0.81
    assert case["webagent_historical_best"] == 0.80
    assert case["milestone_achieved"] is True
    assert case["runs"][0]["usage"] == {
        "input_tokens": 20,
        "output_tokens": 4,
        "total_tokens": 24,
    }
