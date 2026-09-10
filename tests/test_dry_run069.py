"""Deterministic native-runner scenarios and dry-run evidence validation."""

import importlib.util
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_effect_adapters import SubjectModel
from test_effect_trial import _fixture
from test_staged_effect_adapter import StagedSubject, _config, _profile

from famou.effect_adapters import EffectAdapterError, run_subject_adapter
from famou.effect_trial import EffectTrialConfig, EffectTrialRunner

DRY_RUN_PATH = Path(__file__).resolve().parents[1] / "specs/069-webagent-normal-workflow/measurement/dry_run.py"


@pytest.fixture
def dry_module():
    spec = importlib.util.spec_from_file_location("offline_measurement069_dry_run", DRY_RUN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("scenario", ["control_success", "staged_success", "missing_usage", "timeout"])
def test_native_offline_scenario(tmp_path, scenario):
    suite, baseline, public, subject_command, harness_command = _fixture(tmp_path)
    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()))

    class Control(SubjectModel):
        def complete(self, messages, tools=(), timeout=None):
            turn = super().complete(messages, tools, timeout)
            return replace(turn, usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})

    class TimedOut(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            if self.turn == 2:
                self.turn += 1
                raise TimeoutError("offline-unobserved-usage")
            return super().complete(messages, tools, timeout)

    model = (Control() if scenario == "control_success" else TimedOut() if scenario == "timeout"
             else StagedSubject(failure="missing_usage" if scenario == "missing_usage" else None))
    calls = []

    def executor(command, *, cwd, env, timeout):
        del env, timeout
        calls.append(cwd.name)
        request_path = Path(command[-1])
        if cwd.name == "subject":
            config = None if scenario == "control_success" else _config(
                request_path, profile, checkpoint_after_rounds=1 if scenario == "staged_success" else None,
            )
            try:
                run_subject_adapter(
                    request_path, model_runtime=model, model_profile=profile, max_steps=8,
                    workflow_config=config,
                )
            except EffectAdapterError:
                return subprocess.CompletedProcess(command, 2)
        else:
            # Fixture receipt only: no extractor, evaluator, or provider process is invoked.
            request = json.loads(request_path.read_text())
            assert (cwd.parent / "subject/receipt.json").is_file()
            (cwd / "receipt.json").write_text(json.dumps({
                "schema_version": "1", "status": "completed",
                **{key: request[key] for key in ("benchmark", "evaluation_profile", "case", "harness")},
                "extraction_status": "completed", "validity_score": 1.0,
                "overall_score": 0.81, "quality_score": 0.81, "detail_metrics": {},
            }))
        return subprocess.CompletedProcess(command, 0)

    trial = tmp_path / "trial"
    result = EffectTrialRunner(
        suite, baseline, trial, case_sources={"fixture_case": public},
        config=EffectTrialConfig(
            runs_per_case=1, timeout_seconds=10, requested_model=profile.model,
            subject_model_profile_path=profile_path, subject_command=subject_command,
            harness_command=harness_command,
        ), process_executor=executor,
    ).run().to_dict()
    run = result["cases"][0]["runs"][0]
    attempt = trial / run["attempt"]
    subject = attempt / "subject"
    assert json.loads((subject / "solution.json").read_text()) == {"answer": 42}
    assert model.turn == (2 if scenario == "control_success" else 3)
    if scenario.endswith("success"):
        assert calls == ["subject", "harness"] and run["ready"]
        receipt = json.loads((subject / "receipt.json").read_text())
        assert "validity_score" not in receipt and "overall_score" not in receipt
        assert run["usage"]["total_tokens"] == (6 if scenario == "control_success" else 9)
        if scenario == "staged_success":
            state = json.loads((subject / "workflow/state.json").read_text())
            assert state["resume_used"] and state["stage"] == "build_ready"
            checkpoints = sorted((subject / "workflow/checkpoints").glob("*.json"))
            assert len(checkpoints) == 2
            assert json.loads(checkpoints[0].read_text())["stage"] == "checkpointed"
    else:
        assert calls == ["subject"] and not run["ready"]
        assert not (subject / "receipt.json").exists() and not (attempt / "harness").exists()
        assert run["overall_score"] is None and run["validity_score"] is None
        assert run["usage"] is None
        state = json.loads((subject / "workflow/state.json").read_text())
        assert not state["resume_used"]
        restarted = StagedSubject()
        with pytest.raises(EffectAdapterError):
            run_subject_adapter(
                subject / "request.json", model_runtime=restarted, model_profile=profile,
                max_steps=8, workflow_config=_config(subject / "request.json", profile),
            )
        assert restarted.turn == 0


def test_dry_run_requires_actual_test_bytes_in_frozen_manifest(dry_module):
    tests = {"tests/fixture.py": "a" * 64}
    dry_module.verify_test_pins({"frozen_files_sha256": tests}, tests)
    for frozen in ({}, {"tests/fixture.py": "b" * 64}):
        with pytest.raises(dry_module.DryRunError):
            dry_module.verify_test_pins({"frozen_files_sha256": frozen}, tests)


@pytest.mark.parametrize("kind", ["skipped", "failure", "error", "missing", "duplicate"])
def test_dry_run_rejects_incomplete_or_nonpassing_junit(tmp_path, dry_module, monkeypatch, kind):
    monkeypatch.setattr(dry_module, "NODES", ("tests/example.py::test_one",))
    body = '<testcase classname="example" name="test_one">'
    body += f"<{kind}/>" if kind in {"skipped", "failure", "error"} else ""
    body += "</testcase>"
    body = "" if kind == "missing" else body * 2 if kind == "duplicate" else body
    path = tmp_path / "results.xml"
    path.write_text("<testsuite>" + body + "</testsuite>")
    with pytest.raises(dry_module.DryRunError):
        dry_module.parse_results(path)
