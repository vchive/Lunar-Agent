"""Offline tests of the new bindings and the reused native receipt/execution boundary."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from test_effect_trial import _fixture
from test_staged_effect_adapter import StagedSubject

from famou.effect_adapters import EffectAdapterError, famou_case_content_digest, run_subject_adapter
from famou.effect_trial import EffectTrialError, _canonical_bytes, _profile_digest
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn
from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import WorkflowManifest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "specs/072-master-budget-measurement/measurement/adapter.py"


@pytest.fixture
def adapter():
    spec = importlib.util.spec_from_file_location("offline_feature072_adapter", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_loading_ignores_and_preserves_ambient_module_aliases(adapter, monkeypatch):
    sentinels = {name: ModuleType("sentinel_" + name) for name in ("prepare", "worker", "audit", "adapter")}
    for name, value in sentinels.items():
        monkeypatch.setitem(sys.modules, name, value)
    before = {name: sys.modules.get(name) for name in sentinels}
    left, right = adapter.load_worker(), adapter.load_worker()
    campaign = adapter.load_campaign()
    assert left is not right and left.native is not right.native
    assert left.native.verify_bindings is left.verify_bindings
    assert right.native.verify_bindings is right.verify_bindings
    assert campaign.HERE == ADAPTER.parent and campaign.native.CAMPAIGN == adapter.CAMPAIGN
    assert campaign.native.HERE == ADAPTER.parent
    assert {name: sys.modules.get(name) for name in sentinels} == before
    assert all(hasattr(campaign, name) for name in (
        "commands", "EffectTrialConfig", "EffectTrialRunner", "SUBJECT_ENV_NAMES",
        "HARNESS_ENV_NAMES", "REPO", "read_accepted_run", "summarize",
    ))


def test_changed_pinned_helper_is_rejected_before_evaluation(tmp_path, adapter, monkeypatch):
    root = tmp_path / "legacy"
    (root / "measurement").mkdir(parents=True)
    (root / "measurement/worker.py").write_text("raise AssertionError('must not execute')")
    monkeypatch.setattr(adapter, "LEGACY_ROOT", root)
    with pytest.raises(ValueError, match="helper changed"):
        adapter.load_legacy("worker")


def scaffold(tmp_path, adapter, monkeypatch):
    repo = tmp_path.resolve()
    worker, campaign_module = adapter.load_worker(), adapter.load_campaign()
    campaign = repo / ".lunar" / adapter.CAMPAIGN_ID
    inputs = campaign / "inputs"
    inputs.mkdir(parents=True)
    for module in (worker, worker.native, campaign_module, campaign_module.native):
        monkeypatch.setattr(module, "REPO", repo)
    monkeypatch.setattr(campaign_module, "CAMPAIGN", campaign)
    monkeypatch.setattr(campaign_module.native, "CAMPAIGN", campaign)
    monkeypatch.setattr(campaign_module, "HERE", campaign)
    monkeypatch.setattr(campaign_module.native, "HERE", campaign)
    monkeypatch.setattr(campaign_module.native, "commands", worker.commands)
    files = []
    for owner, path in ((worker, repo / "measurement/worker.py"),
                        (worker.native, repo / "legacy/worker.py")):
        path.parent.mkdir(parents=True)
        path.write_text("# inert binding fixture\n")
        monkeypatch.setattr(owner, "__file__", str(path))
        files.append(path)
    for relative in ("src/famou/fixture.py", worker.HARNESS_PYTHON, ".venv/bin/lunar-agent"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# never dispatched fixture\n")
        files.append(path)
    source_files = {"src/famou/fixture.py": worker.file_sha256(repo / "src/famou/fixture.py")}
    source_sha = worker.canonical_sha256(source_files)
    profile = ModelProfile("offline-glm", "glm-5.2", max_steps=200, timeout_seconds=5400,
                           max_total_tokens=8000000, thinking_budget=0)
    profile_sha = _profile_digest(profile)
    worker.write_new(inputs / "profile.json", profile.to_dict())
    cases = {}
    for key in dict.fromkeys(key for _, key in adapter.ORDER):
        suite_path, baseline_path, _, _, _ = _fixture(repo / key)
        suite, baseline = json.loads(suite_path.read_text()), json.loads(baseline_path.read_text())
        private = repo / key / "private"
        (private / "tests").mkdir(parents=True)
        (private / "instruction.md").write_text("Solve the offline fixture.")
        for name in ("extractor_agent.py", "evaluator.py"):
            (private / "tests" / name).write_text("# not executed\n")
        case = suite["cases"][0]
        case.update(key=key, digest=famou_case_content_digest(private), harness={
            "extractor_sha256": worker.file_sha256(private / "tests/extractor_agent.py"),
            "evaluator_sha256": worker.file_sha256(private / "tests/evaluator.py"),
        })
        baseline.update(source="company-platform", provenance={"source": "company-platform", "adapter": "agentserver"})
        baseline["model"]["requested"] = "glm-5.2"
        baseline["cases"][0].update({field: case[field] for field in ("key", "digest", "harness")})
        worker.write_new(inputs / f"{key}-suite.json", suite)
        worker.write_new(inputs / f"{key}-baseline.json", baseline)
        cases[key] = {"suite": suite, "public_root_rel": f"{key}/case", "private_root_rel": f"{key}/private"}
    slots = []
    for index, (budget_arm, key) in enumerate(adapter.ORDER, 1):
        request_sha = worker.request_sha256(cases[key]["suite"], profile_sha)
        control = WorkflowManifest(
            run_id=f"{campaign.name}-slot-{index:03d}", attempt_id=f"slot-{index:03d}-attempt-001",
            source_sha256=source_sha, suite_key="famou-bench", case_key=key,
            request_sha256=request_sha, model_profile_sha256=profile_sha,
            ceilings={"max_wall_seconds": 5400, "max_tool_steps": 200,
                      "max_total_tokens": 8000000, "max_cost_micros": None},
        )
        workflow = StagedWorkflowConfig(control, StagePolicy.from_dict(adapter.POLICIES[budget_arm])).to_dict()
        worker.write_new(inputs / f"slot-{index:03d}-workflow.json", workflow)
        slots.append({"index": index, "arm": "S", "budget_arm": budget_arm, "case_key": key,
                      "request_sha256": request_sha, "workflow_config": workflow})
    env = {"FAMOU_MODEL_ENDPOINT": "https://subject.invalid", "FAMOU_API_KEY": "fixture-secret",
           "ANTHROPIC_BASE_URL": "https://harness.invalid", "ANTHROPIC_AUTH_TOKEN": "fixture-extractor",
           "ANTHROPIC_MODEL": "glm-5.2"}
    manifest = {
        "campaign_id": campaign.name, "planned_attempts": 4, "execution": copy.deepcopy(adapter.EXECUTION),
        "policies": copy.deepcopy(adapter.POLICIES), "source_files_sha256": source_files,
        "source_sha256": source_sha, "profile": profile.to_dict(), "profile_sha256": profile_sha,
        "cases": cases, "slots": slots, "frozen_files_sha256": {
            path.relative_to(repo).as_posix(): worker.file_sha256(path) for path in [*files, *inputs.iterdir()]
        }, "endpoints": {name: hashlib.sha256(env[name].encode()).hexdigest()
                         for name in ("FAMOU_MODEL_ENDPOINT", "ANTHROPIC_BASE_URL")},
    }
    worker.write_new(campaign / "manifest.json", manifest)
    digest = worker.file_sha256(campaign / "manifest.json")
    (campaign / "manifest.sha256").write_text(digest + "\n")
    return worker, campaign_module, campaign, manifest, digest, profile, env


def test_four_exact_bindings_use_staged_commands_and_shared_ceilings(tmp_path, adapter, monkeypatch):
    worker, _, campaign, manifest, digest, _, _ = scaffold(tmp_path, adapter, monkeypatch)
    for slot in manifest["slots"]:
        worker.verify_bindings(campaign / "manifest.json", campaign, manifest, digest, slot, require_started=False)
        subject, harness = worker.commands(manifest, campaign, slot)
        path = subject[subject.index("--workflow-config") + 1]
        assert Path(path) == campaign / "inputs" / f"slot-{slot['index']:03d}-workflow.json"
        assert subject[subject.index("--timeout") + 1] == "5400"
        assert subject[subject.index("--max-steps") + 1] == "200"
        assert "--workflow-config" not in harness
    assert manifest["slots"][0]["request_sha256"] == manifest["slots"][2]["request_sha256"]
    assert manifest["slots"][1]["request_sha256"] == manifest["slots"][3]["request_sha256"]


@pytest.mark.parametrize("alteration", ["arm", "budget", "order", "policy", "workflow", "identity", "source", "input", "private", "missing_pin", "terminal"])
def test_worker_rejects_changed_budget_identity_or_frozen_bytes(tmp_path, adapter, monkeypatch, alteration):
    worker, _, campaign, manifest, digest, _, _ = scaffold(tmp_path, adapter, monkeypatch)
    slot = manifest["slots"][0]
    if alteration in {"arm", "budget", "order"}:
        field, value = {"arm": ("arm", "M"), "budget": ("budget_arm", "master_1200"),
                        "order": ("index", 3)}[alteration]
        slot[field] = value
    elif alteration == "policy":
        manifest["policies"]["master_300"]["master_seconds"] = 301
    elif alteration in {"workflow", "identity"}:
        workflow = slot["workflow_config"]
        if alteration == "workflow":
            workflow["policy"]["master_seconds"] = 1200
        else:
            workflow["manifest"]["attempt_id"] = "another-attempt"
        path = campaign / "inputs/slot-001-workflow.json"
        path.write_bytes(_canonical_bytes(workflow))
        manifest["frozen_files_sha256"][path.relative_to(tmp_path).as_posix()] = worker.file_sha256(path)
    elif alteration in {"source", "input", "private"}:
        path = {"source": tmp_path / "src/famou/fixture.py", "input": campaign / "inputs/profile.json",
                "private": tmp_path / slot["case_key"] / "private/tests/evaluator.py"}[alteration]
        path.write_text("changed")
    elif alteration == "missing_pin":
        del manifest["frozen_files_sha256"][Path(worker.__file__).relative_to(tmp_path).as_posix()]
    else:
        worker.write_new(campaign / "terminated.json", {})
    # Repin the synthetic registration so rejection tests its content/bindings, not a stale digest.
    path = campaign / "manifest.json"
    path.write_bytes(_canonical_bytes(manifest))
    digest = worker.file_sha256(path)
    (campaign / "manifest.sha256").write_text(digest + "\n")
    worker.write_new(campaign / "started.json", {"manifest_sha256": digest})
    worker.write_new(campaign / "slot-001-started.json", {"index": 1, "manifest_sha256": digest})
    with pytest.raises((EffectTrialError, ValueError, KeyError)):
        worker.verify_bindings(path, campaign, manifest, digest, slot)


class Subject(StagedSubject):
    model = "glm-5.2"

    def __init__(self, scenario):
        super().__init__()
        self.scenario, self.timeouts = scenario, []

    def complete(self, messages, tools=(), timeout=None):
        self.timeouts.append(timeout)
        if self.turn == 0 and self.scenario == "master_timeout":
            self.turn += 1
            raise TimeoutError("offline timeout")
        if self.turn == 0 and self.scenario == "invalid_plan":
            self.turn += 1
            return ModelTurn("invalid JSON", response_model="glm-5.2",
                             usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
        return replace(super().complete(messages, tools, timeout), response_model="glm-5.2")


@pytest.mark.parametrize("index", [1, 2])
@pytest.mark.parametrize("scenario", ["success", "master_timeout", "invalid_plan", "failed_extraction"])
def test_native_staged_subject_and_receipt_gate(tmp_path, adapter, monkeypatch, index, scenario):
    worker, dispatcher, campaign, manifest, digest, profile, env = scaffold(tmp_path, adapter, monkeypatch)
    slot = manifest["slots"][index - 1]
    root = campaign / f"slots/{index:03d}"
    root.mkdir(parents=True)
    worker.write_new(campaign / "started.json", {"manifest_sha256": digest})
    worker.write_new(campaign / f"slot-{index:03d}-started.json", {"index": index, "manifest_sha256": digest})
    worker.write_new(root / "worker-started.json", {"index": index, "manifest_sha256": digest})
    model, phases = Subject(scenario), []

    def process(command, *, cwd, env, timeout):
        phases.append(cwd.name)
        request_path = Path(command[-1])
        if cwd.name == "subject":
            assert timeout == 5430 and "ANTHROPIC_AUTH_TOKEN" not in env
            config = StagedWorkflowConfig.load(Path(command[command.index("--workflow-config") + 1]))
            try:
                run_subject_adapter(request_path, model_runtime=model, model_profile=profile,
                                    max_steps=200, timeout=5400, workflow_config=config)
            except EffectAdapterError:
                return subprocess.CompletedProcess(command, 2)
        else:
            assert timeout == 3630 and "FAMOU_API_KEY" not in env
            request = json.loads(request_path.read_text())
            assert (cwd.parent / "subject/receipt.json").is_file()
            failed = scenario == "failed_extraction"
            worker.write_new(cwd / "receipt.json", {
                "schema_version": "1", "status": "completed",
                **{key: request[key] for key in ("benchmark", "evaluation_profile", "case", "harness")},
                "extraction_status": "failed" if failed else "completed", "validity_score": 0 if failed else 1,
                "overall_score": 0 if failed else 1.2, "quality_score": None, "detail_metrics": {},
            })
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(worker.native, "_default_executor", process)
    executor = worker.RegisteredExecutor(campaign / "manifest.json", campaign, manifest, digest, slot)
    runner = worker.build_runner(manifest, campaign, slot, env, process_executor=executor)
    run = runner.run().to_dict()["cases"][0]["runs"][0]
    subject = root / "trial" / run["attempt"] / "subject"
    budget = manifest["policies"][slot["budget_arm"]]["master_seconds"]
    assert budget - 2 < model.timeouts[0] <= budget
    success = scenario in {"success", "failed_extraction"}
    assert phases == (["subject", "harness"] if success else ["subject"])
    assert (subject / "workflow/master.json").is_file() == success
    assert (subject / "workflow/session-transcript.jsonl").is_file() == success
    assert (subject / "receipt.json").is_file() == success
    if success:
        assert "MODEL_PLAN_SENTINEL" in str(model.messages[1])
        assert run["usage"]["total_tokens"] == 9 and run["interaction_turns"] == 3
    else:
        assert run["overall_score"] is None and run["usage"] is None
    record_path = root / f"trial/cases/{slot['case_key']}/runs/001/record.json"
    record = worker.read_json(record_path)
    outcome = {"index": index, "arm": "S", "case_key": slot["case_key"], "manifest_sha256": digest,
               "status": "terminated", "record_status": record["status"], "worker_returncode": 0,
               "record_sha256": hashlib.sha256(_canonical_bytes(record)).hexdigest(),
               "report_sha256": worker.file_sha256(root / "trial/report.json")}
    worker.write_new(root / "outcome.json", outcome)
    worker.write_new(root / "worker-terminated.json", {"index": index, "manifest_sha256": digest,
                     "returncode": 0, "outcome_sha256": worker.file_sha256(root / "outcome.json")})
    worker.write_new(campaign / f"slot-{index:03d}-terminated.json", {"index": index,
                     "manifest_sha256": digest, "exit_code": 0, "failure": None})
    summary = dispatcher.summarize()
    row = summary["slots"][index - 1]
    assert row["overall_score"] == (1.2 if scenario == "success" else None)
    assert summary["budget_arms"][slot["budget_arm"]]["valid_solution_rate"] == (0.5 if scenario == "success" else 0)
    assert summary["planned_attempts"] == 4 and not summary["all_slots_terminated"]
    assert summary["pooled_quality_mean"] is None
    with pytest.raises(EffectTrialError):
        runner.run()
    assert "fixture-secret" not in json.dumps(summary)
    report_path = root / "trial/report.json"
    report_path.write_text("{}")
    with pytest.raises(ValueError):
        dispatcher.summarize()


def test_private_wave_barrier_and_exclusive_slot_markers(tmp_path, adapter, monkeypatch):
    campaign = adapter.load_campaign()
    finished, calls, lock = set(), [], threading.Lock()

    def run(slot, environment, digest):
        with lock:
            if slot["index"] > 2:
                assert finished >= {1, 2}
            calls.append(slot["index"])
            finished.add(slot["index"])
        return slot["index"]

    monkeypatch.setattr(campaign.native, "run_slot", run)
    assert campaign.execute_waves({"execution": {"waves": [[1, 2], [3, 4]]},
                                  "slots": [{"index": i} for i in range(1, 5)]}, {}, "a" * 64) == [1, 2, 3, 4]
    assert sorted(calls) == [1, 2, 3, 4]
    monkeypatch.setattr(campaign.native, "CAMPAIGN", tmp_path.resolve())
    dispatched = []
    monkeypatch.setattr(campaign.native, "execute_slot", lambda *args, **kwargs: dispatched.append(args) or 0)
    campaign.run_slot({"index": 1}, {}, "a" * 64)
    with pytest.raises(FileExistsError):
        campaign.run_slot({"index": 1}, {}, "a" * 64)
    assert len(dispatched) == 1
    assert str(ADAPTER.parent / "worker.py") in dispatched[0][0]


@pytest.mark.parametrize("changed", [None, "uncommitted_script", "unmirrored_report", "failed_dry_run"])
def test_launch_seals_bytes_and_acquires_ownership_before_credentials(tmp_path, adapter, monkeypatch, changed):
    campaign = adapter.load_campaign()
    here, root = tmp_path / "specs/measurement", tmp_path / "campaign"
    here.mkdir(parents=True)
    root.mkdir()
    monkeypatch.setattr(campaign, "HERE", here)
    monkeypatch.setattr(campaign, "REPO", tmp_path)
    monkeypatch.setattr(campaign, "CAMPAIGN", root)
    checked, configured, dispatched = [], [], []
    audit = ModuleType("offline_audit")
    audit.audit = lambda *args: {"passed": True}
    original_import = campaign.__dict__["__builtins__"]["__import__"]

    def fixture_import(name, *args, **kwargs):
        return audit if name == "audit" else original_import(name, *args, **kwargs)

    monkeypatch.setitem(campaign.__dict__["__builtins__"], "__import__", fixture_import)
    script = tmp_path / "specs/frozen.py"
    script.write_text("# frozen\n")
    environment = {"FAMOU_MODEL_ENDPOINT": "https://subject.invalid", "FAMOU_API_KEY": "fixture-secret",
                   "ANTHROPIC_BASE_URL": "https://harness.invalid", "ANTHROPIC_AUTH_TOKEN": "fixture-extractor",
                   "ANTHROPIC_MODEL": "glm-5.2"}
    manifest = {"campaign_id": root.name, "frozen_files_sha256": {"specs/frozen.py": campaign.sha(script)},
                "endpoints": {name: hashlib.sha256(environment[name].encode()).hexdigest()
                              for name in ("FAMOU_MODEL_ENDPOINT", "ANTHROPIC_BASE_URL")}}
    for directory in (here, root):
        campaign.write_new(directory / "manifest.json", manifest)
    digest = campaign.sha(here / "manifest.json")
    for name in ("prelaunch-audit.json", "dry-run.json"):
        for directory in (here, root):
            campaign.write_new(directory / name, {"passed": changed != "failed_dry_run" or name != "dry-run.json",
                                                  "manifest_sha256": digest, "model_calls": 0})
    committed = {path.relative_to(tmp_path).as_posix(): path.read_bytes()
                 for path in [script, *here.iterdir()]}

    def git(arguments, **kwargs):
        checked.append(arguments)
        if arguments[1] == "rev-parse":
            return "a" * 40
        return committed[arguments[2].removeprefix("HEAD:")]

    monkeypatch.setattr(campaign.subprocess, "check_output", git)
    loader = ModuleType("offline_credentials")

    def load_environment():
        assert (root / "started.json").is_file()
        configured.append(True)
        return environment

    loader.load_environment = load_environment
    spec = ModuleType("offline_loader_spec")
    spec.loader = ModuleType("offline_loader")
    spec.loader.exec_module = lambda module: None
    monkeypatch.setattr(campaign.importlib.util, "spec_from_file_location", lambda *args: spec)
    monkeypatch.setattr(campaign.importlib.util, "module_from_spec", lambda spec: loader)
    monkeypatch.setattr(campaign, "execute_waves", lambda *args: dispatched.append(args) or [])
    monkeypatch.setattr(campaign, "summarize", lambda: {"fixture": True})
    if changed == "uncommitted_script":
        script.write_text("# changed after registration\n")
    elif changed == "unmirrored_report":
        (root / "prelaunch-audit.json").write_text("{}")
    if changed:
        with pytest.raises(ValueError):
            campaign.launch()
        assert not configured and not dispatched and not (root / "started.json").exists()
    else:
        campaign.launch()
        assert len(configured) == len(dispatched) == 1
        assert ["git", "show", "HEAD:specs/frozen.py"] in checked
        with pytest.raises(FileExistsError):
            campaign.launch()
        assert len(configured) == len(dispatched) == 1
        assert "fixture-secret" not in (root / "started.json").read_text()
