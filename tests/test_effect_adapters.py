import hashlib
import json
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Self
from urllib.error import HTTPError

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
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, RuntimeResult, ToolCall


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
@pytest.mark.parametrize("failure", ["public", "http", "runtime", "steps"])
def test_subject_failures_leave_bound_safe_diagnostics(
    tmp_path: Path, mode: str, failure: str
) -> None:
    request = _subject_request(tmp_path / "subject")
    payload = json.loads(request.read_text())
    if mode == "deep_evolution":
        payload.update(
            mode=mode, round_index=1, outer_rounds=5, previous_evaluation=None,
            receipt_path="receipts/001.json",
        )
        _write_json(request, payload)
    sentinel = "PRIVATE-CREDENTIAL-PROMPT-BODY-SENTINEL"
    observed_prompts = []

    class FailingSubject(SubjectModel):
        def complete(self, messages, tools=(), timeout=None):
            observed_prompts.append(str(messages))
            self.turn += 1
            if failure == "http":
                raise RuntimeExecutionError(sentinel) from HTTPError(
                    "https://private.invalid/", 429, sentinel, {}, None,
                )
            if failure == "runtime":
                raise RuntimeError(sentinel)
            if failure == "public" and self.turn == 2:
                return ModelTurn("done")
            return ModelTurn("", (ToolCall(
                "private-call", "write_file",
                {"path": "case/solve.py" if failure == "public" else "solve.py",
                 "content": sentinel},
            ),))

    with pytest.raises(EffectAdapterError):
        run_subject_adapter(request, model_runtime=FailingSubject(), max_steps=1)

    diagnostic_path = (request.parent / payload["receipt_path"]).with_suffix(".failure.json")
    encoded = diagnostic_path.read_bytes()
    diagnostic = json.loads(encoded)
    assert len(encoded) <= 4096
    assert sentinel.encode() not in encoded
    assert b"private.invalid" not in encoded and b"private-call" not in encoded
    assert "score" not in diagnostic and not (request.parent / payload["receipt_path"]).exists()
    assert diagnostic["request_sha256"] == _sha(request)
    assert diagnostic["mode"] == mode
    assert diagnostic["run_index"] == 1
    assert diagnostic["round_index"] == (1 if mode == "deep_evolution" else None)
    assert diagnostic["code"] == {
        "public": "public_file_set_changed", "http": "model_http_failed",
        "runtime": "model_failed", "steps": "step_limit",
    }[failure]
    assert diagnostic["http_status"] == (429 if failure == "http" else None)
    assert diagnostic["model_turns"] == (2 if failure in {"public", "steps"} else 0)
    assert diagnostic["tool_steps"] == (1 if failure in {"public", "steps"} else 0)
    assert "entire `case/` tree is read-only" in observed_prompts[0]
    assert "solve.py" in observed_prompts[0] and "case/data/" in observed_prompts[0]


@pytest.mark.parametrize("failure", ["tool", "timeout", "receipt"])
def test_subject_diagnostic_classifies_additional_failure_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    from famou.agent_loop import AgentLoopRuntime
    from famou.tools import LocalToolRegistry

    request = _subject_request(tmp_path / "subject")
    secret = "SECRET-PRIVATE-ERROR-SENTINEL"

    def fail_tool(*args, **kwargs):
        raise RuntimeError(secret)

    class TimeoutSubject(SubjectModel):
        def complete(self, messages, tools=(), timeout=None):
            raise TimeoutError(secret)

    if failure == "tool":
        monkeypatch.setattr(LocalToolRegistry, "execute", fail_tool)
    elif failure == "receipt":
        monkeypatch.setattr(
            AgentLoopRuntime, "run",
            lambda *args, **kwargs: RuntimeResult("done", metadata={"turns": secret}),
        )
    with pytest.raises((EffectAdapterError, ValueError)):
        run_subject_adapter(
            request, model_runtime=TimeoutSubject() if failure == "timeout" else SubjectModel(),
        )
    content = (request.parent / "receipt.failure.json").read_bytes()
    diagnostic = json.loads(content)
    assert secret.encode() not in content
    assert diagnostic["stage"] == {"tool": "tool", "timeout": "model", "receipt": "receipt"}[failure]
    assert diagnostic["code"] == {"tool": "tool_failed", "timeout": "timeout", "receipt": "receipt_invalid"}[failure]
    assert not (request.parent / "receipt.json").exists()


@pytest.mark.parametrize("stage", ["classification", "publication"])
def test_diagnostic_failure_preserves_original_subject_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    import famou.subject_diagnostics as diagnostics

    request = _subject_request(tmp_path / "subject")
    original = RuntimeError("original private failure")

    class FailingSubject(SubjectModel):
        def complete(self, messages, tools=(), timeout=None):
            raise original

    def fail_publication(*args, **kwargs):
        raise OSError("publication denied")

    if stage == "publication":
        monkeypatch.setattr(diagnostics, "publish_diagnostic", fail_publication)
    else:
        monkeypatch.setattr(diagnostics.SubjectDiagnosticObserver, "failure", fail_publication)
    with pytest.raises(EffectAdapterError, match="subject runtime failed") as caught:
        run_subject_adapter(request, model_runtime=FailingSubject())
    assert caught.value.__cause__ is original
    assert not (request.parent / "receipt.json").exists()


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


def test_builtin_subject_profile_emits_credential_free_provenance(tmp_path: Path) -> None:
    request = _subject_request(tmp_path / "subject")
    profile = ModelProfile(
        name="fixture-profile",
        model="gpt-5.6-sol",
        max_steps=4,
        timeout_seconds=10,
        max_total_tokens=200,
        input_cost_per_1k_micros=100,
        output_cost_per_1k_micros=100,
    )
    profile_digest = hashlib.sha256(
        json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["model_profile_sha256"] = profile_digest
    request.write_text(json.dumps(payload), encoding="utf-8")

    receipt = run_subject_adapter(
        request,
        model_runtime=SubjectModel(),
        max_steps=8,
        model_profile=profile,
    )

    assert receipt["model_profile_sha256"] == profile_digest
    assert receipt["cost_micros"] == 18
    assert "score" not in json.dumps(receipt)
    assert "api_key" not in json.dumps(receipt).lower()


def test_builtin_subject_profile_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    request = _subject_request(tmp_path / "subject")
    profile = ModelProfile(name="fixture-profile", model="gpt-5.6-sol")
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["model_profile_sha256"] = "0" * 64
    request.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectAdapterError, match="profile digest"):
        run_subject_adapter(request, model_runtime=SubjectModel(), model_profile=profile)


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
@pytest.mark.parametrize("usage", [None, {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}])
def test_subject_budget_rejects_unaccounted_or_exhausted_tool_turn_before_receipt(
    tmp_path: Path, mode: str, usage: dict[str, int] | None
) -> None:
    request = _subject_request(tmp_path / "subject")
    profile = ModelProfile("bounded", "gpt-5.6-sol", max_total_tokens=10)
    payload = json.loads(request.read_text())
    payload["model_profile_sha256"] = hashlib.sha256(
        json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if mode == "deep_evolution":
        payload.update(mode=mode, round_index=1, outer_rounds=5, previous_evaluation=None)
    _write_json(request, payload)

    class UnaccountedSubject(SubjectModel):
        def complete(self, messages, tools=(), timeout=None):
            self.turn += 1
            if self.turn > 1:
                return ModelTurn("done", usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            return ModelTurn(
                "",
                (ToolCall("write", "write_file", {"path": "solution.json", "content": "{}"}),),
                usage=usage,
            )

    model = UnaccountedSubject()
    with pytest.raises(EffectAdapterError, match="subject runtime failed"):
        run_subject_adapter(request, model_runtime=model, model_profile=profile)
    assert model.turn == 1
    assert not (request.parent / "solution.json").exists()
    assert not (request.parent / payload["receipt_path"]).exists()


def test_builtin_subject_rejects_uppercase_profile_digest(tmp_path: Path) -> None:
    request = _subject_request(tmp_path / "subject")
    profile = ModelProfile(name="fixture-profile", model="gpt-5.6-sol")
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["model_profile_sha256"] = "A" * 64
    request.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectAdapterError, match="profile digest"):
        run_subject_adapter(request, model_runtime=SubjectModel(), model_profile=profile)


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


def _results_with_adapter(adapter: str, *, runtime_adapter: str | None = None) -> dict:
    payload = _results()
    payload["experiment"].update(
        {
            "adapter_kind": adapter,
            "request": {"adapter_request": {"kind": adapter}},
            "configuration": {
                "adapter": adapter,
                "adapter_release": {"adapter_kind": adapter},
            },
        }
    )
    for row in payload["results"]:
        row["runtime_telemetry"] = {
            "adapter_request": {
                "receipt": {"adapter_kind": runtime_adapter or adapter},
            }
        }
    return payload


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


def test_offline_converter_rejects_modern_agentserver_export(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(
        tmp_path / "results.json", _results_with_adapter("agentserver")
    )
    output = tmp_path / "baseline.json"

    with pytest.raises(EffectAdapterError, match="webagent adapter"):
        convert_fm_eval_baseline(
            results_path,
            suite_path,
            output,
            experiment_id="fmexp-fixture",
            requested_model="gpt-5.6-sol",
            effective_model="openai/gpt-5.6-sol",
            model_evidence="not_observable",
        )

    assert not output.exists()


def test_offline_converter_accepts_consistent_webagent_evidence(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(
        tmp_path / "results.json", _results_with_adapter("webagent")
    )
    output = tmp_path / "baseline.json"

    converted = convert_fm_eval_baseline(
        results_path,
        suite_path,
        output,
        experiment_id="fmexp-fixture",
        requested_model="gpt-5.6-sol",
        effective_model="openai/gpt-5.6-sol",
        model_evidence="not_observable",
    )

    assert TrialBaseline.from_dict(converted).cases[0].best() == 0.80
    assert output.is_file()


def test_offline_converter_accepts_explicit_company_platform_evidence(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(
        tmp_path / "results.json", _results_with_adapter("company-platform")
    )
    output = tmp_path / "baseline.json"

    converted = convert_fm_eval_baseline(
        results_path,
        suite_path,
        output,
        experiment_id="fmexp-fixture",
        requested_model="gpt-5.6-sol",
        effective_model="openai/gpt-5.6-sol",
        model_evidence="not_observable",
        adapter_kind="company-platform",
        baseline_source="company-platform",
    )

    parsed = TrialBaseline.from_dict(converted)
    assert parsed.source == "company-platform"
    assert parsed.provenance is not None
    assert parsed.provenance.to_dict() == {
        "source": "company-platform",
        "adapter": "company-platform",
    }
    assert parsed.cases[0].best() == 0.80


def test_offline_converter_rejects_conflicting_adapter_evidence(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(
        tmp_path / "results.json",
        _results_with_adapter("webagent", runtime_adapter="agentserver"),
    )
    output = tmp_path / "baseline.json"

    with pytest.raises(EffectAdapterError, match="conflicting adapter evidence"):
        convert_fm_eval_baseline(
            results_path,
            suite_path,
            output,
            experiment_id="fmexp-fixture",
            requested_model="gpt-5.6-sol",
            effective_model="openai/gpt-5.6-sol",
            model_evidence="not_observable",
        )

    assert not output.exists()


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


def test_effect_baseline_cli_converts_company_platform_results(
    tmp_path: Path, capsys
) -> None:
    public, private = _make_case(tmp_path)
    suite_path = _write_json(tmp_path / "suite.json", _make_suite(public, private))
    results_path = _write_json(
        tmp_path / "results.json", _results_with_adapter("company-platform")
    )
    output = tmp_path / "company-baseline.json"

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
            "--adapter-kind",
            "company-platform",
            "--baseline-source",
            "company-platform",
            "--json",
        ]
    )

    assert status == 0
    assert json.loads(capsys.readouterr().out)["source"] == "company-platform"
    parsed = TrialBaseline.from_dict(json.loads(output.read_text(encoding="utf-8")))
    assert parsed.provenance is not None
    assert parsed.provenance.source == "company-platform"
    assert parsed.provenance.adapter == "company-platform"


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


def test_profile_failure_preserves_candidate_without_receipt_harness_or_score(tmp_path: Path) -> None:
    public, private = _make_case(tmp_path)
    suite = _make_suite(public, private)
    suite_path = _write_json(tmp_path / "suite.json", suite)
    results_path = _write_json(tmp_path / "results.json", _results())
    baseline_path = tmp_path / "baseline.json"
    convert_fm_eval_baseline(
        results_path, suite_path, baseline_path, experiment_id="fmexp-fixture",
        requested_model="gpt-5.6-sol", effective_model="openai/gpt-5.6-sol",
        model_evidence="not_observable",
    )
    profile = ModelProfile(
        "bounded-candidate", "gpt-5.6-sol", timeout_seconds=10, max_steps=4,
        max_total_tokens=20,
    )
    profile_path = _write_json(tmp_path / "profile.json", profile.to_dict())
    harness_marker = tmp_path / "harness-was-invoked"
    trial = tmp_path / "trial-preserved-candidate"
    lunar = Path(sys.executable).parent / "lunar-agent"

    # The HTTP fixture writes candidate files using 12 tokens, then returns a final response
    # costing another 12. A retained candidate cannot authorize scoring after that overshoot.
    with EffectModelServer() as server:
        report = EffectTrialRunner(
            suite_path, baseline_path, trial,
            case_sources={"case-a": public},
            config=EffectTrialConfig(
                runs_per_case=1, timeout_seconds=10, requested_model="gpt-5.6-sol",
                subject_model_profile_path=profile_path,
                subject_command=(
                    str(lunar), "effect-subject", "--endpoint", server.url,
                    "--model", "gpt-5.6-sol", "--max-steps", "4",
                ),
                harness_command=(
                    str(Path(sys.executable).resolve()), "-c",
                    "import sys; from pathlib import Path; Path(sys.argv[1]).write_text('unexpected')",
                    str(harness_marker),
                ),
            ),
        ).run().to_dict()

    assert EffectModelHandler.requests == 2
    case = report["cases"][0]
    run = case["runs"][0]
    attempt = trial / run["attempt"]
    assert json.loads((attempt / "subject" / "solution.json").read_text()) == {"answer": 42}
    assert (attempt / "subject" / "_agent_summary.md").read_text() == "Final: solution.json"
    assert not (attempt / "subject" / "receipt.json").exists()
    assert not (attempt / "harness").exists()
    assert not harness_marker.exists()
    assert run["status"] == "failed" and run["ready"] is False
    assert case["lunar_best"] is None
    for field in ("validity_score", "overall_score", "quality_score", "usage", "cost_micros"):
        assert run[field] is None
    diagnostic = json.loads((attempt / "diagnostics" / "subject-failure.json").read_text())
    assert diagnostic["schema_version"] == "2"
    assert diagnostic["stage"] == "runtime"
    assert diagnostic["code"] == "budget_exceeded"
    assert diagnostic["budget"] == {
        "limit": "max_total_tokens",
        "state": "exceeded",
        "maximum": 20,
        "accepted_usage": {
            "input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
            "cost_micros": None, "rounds": 1,
        },
        "observed_usage": {
            "input_tokens": 20, "output_tokens": 4, "total_tokens": 24,
            "cost_micros": None, "rounds": 2,
        },
        "trigger_recorded": False,
        "usage_completeness": "partial",
    }
    # Counters remain emitted events; the rejected response is only in observed_usage.
    assert diagnostic["model_turns"] == 1 and diagnostic["tool_steps"] == 2
    assert "score" not in json.dumps(diagnostic)
