"""A solve deadline remains authoritative across generation, execution and scoring."""
from __future__ import annotations

from dataclasses import replace

import pytest
from test_agent_bundle_generation import BundleFixtureAgent, _generator
from test_agent_evolution import EvaluatorFixtureAgent, FixtureAgent, _contract
from test_automatic_solve_bundle import _fixture
from test_bundle_population import build_context, draft_for_score
from test_candidate_execution_runner import _setup

from famou.agent_evolution import AgentCandidateGenerator, AgentEvaluatorEnsemble
from famou.automatic_solve_bundle import prepare_automatic_solve_bundle
from famou.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from famou.candidate_execution_evidence import run_candidate_execution_recorded
from famou.candidate_execution_runner import CandidateExecutionRunnerError, run_candidate_execution
from famou.evolution import (
    CandidateArchive,
    CommandCandidateRunner,
    GenerationRequest,
    PopulationStrategy,
)


def control_fixture():
    now = [0.0]
    return now, SolveExecutionControl(1, clock=lambda: now[0])


@pytest.mark.parametrize("value", [True, "1", 0, -1, float("nan"), float("inf")])
def test_operational_execution_timeout_rejects_invalid_values_before_launch(tmp_path, monkeypatch, value):
    admission, plan, workspace, inputs = _setup(tmp_path)
    monkeypatch.setattr("famou.candidate_execution_runner._bounded_process", lambda *a, **k: pytest.fail("launch"))
    with pytest.raises(CandidateExecutionRunnerError):
        run_candidate_execution(admission, plan=plan, workspace_path=workspace,
                                input_path=inputs, timeout_seconds=value)


@pytest.mark.parametrize("timeout,expected", [(0.002, 0.002), (5, 2)])
def test_operational_execution_timeout_narrows_without_changing_pins(tmp_path, monkeypatch, timeout, expected):
    admission, plan, workspace, inputs = _setup(tmp_path)
    pinned = plan.digest(), admission.digest()
    observed = []

    def process(*args, **kwargs):
        observed.append(kwargs["timeout"])
        return "", "", "succeeded", 0, None

    monkeypatch.setattr("famou.candidate_execution_runner._bounded_process", process)
    result = run_candidate_execution(admission, plan=plan, workspace_path=workspace,
                                     input_path=inputs, timeout_seconds=timeout)
    assert observed == [expected]
    assert (result.workspace_plan_sha256, result.admission_sha256) == pinned
    assert (plan.digest(), admission.digest()) == pinned


@pytest.mark.parametrize("stop", ["budget", "cancel"])
def test_execution_record_preserves_typed_stop(tmp_path, monkeypatch, stop):
    admission, plan, workspace, inputs = _setup(tmp_path)
    now, control = control_fixture()
    now[0] = 2
    if stop == "cancel":
        control.cancel()

    def stopped(*args, **kwargs):
        control.check("candidate_execution")

    monkeypatch.setattr("famou.candidate_execution_evidence.run_candidate_execution", stopped)
    error = SolveExecutionBudgetExceeded if stop == "budget" else SolveExecutionCancelled
    with pytest.raises(error):
        run_candidate_execution_recorded(admission, plan=plan, workspace_path=workspace,
                                         input_path=inputs, attempt_path=tmp_path / "attempt")
    assert not (tmp_path / "attempt" / "completed.json").exists()


@pytest.mark.parametrize("configured,timeout,expected", [(2, 0.001, 0.001), (2, 10, 2), (0.02, None, 0.05)])
def test_single_file_runner_preserves_legacy_floor_but_never_enlarges_operational_timeout(
    tmp_path, monkeypatch, configured, timeout, expected,
):
    source = tmp_path / "main.py"
    source.write_text("pass\n")
    observed = []

    class Process:
        returncode = 0

        def communicate(self, *, timeout):
            observed.append(timeout)
            return "", ""

        def poll(self):
            return self.returncode

    monkeypatch.setattr("famou.evolution.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr("famou.evolution._kill_candidate_process_group", lambda process: True)
    runner = CommandCandidateRunner(("/bin/sh",), timeout_seconds=configured)
    assert runner.run(source, tmp_path, timeout=timeout).status == "succeeded"
    assert observed == [expected]


def test_agent_evaluator_ensemble_does_not_convert_solve_timeout_to_invalid_score(tmp_path):
    now, control = control_fixture()
    adapter = EvaluatorFixtureAgent("{}")

    def run(request):
        now[0] = 2
        control.check("evaluation")

    adapter.run = run
    source = tmp_path / "main.py"
    source.write_text("pass\n")
    ensemble = AgentEvaluatorEnsemble((adapter, EvaluatorFixtureAgent("{}")),
                                     required_capabilities=("read_files",))
    ensemble.set_remaining_timeout(control.check)
    with pytest.raises(SolveExecutionBudgetExceeded):
        ensemble(source, _contract())


@pytest.mark.parametrize("stage", ["initialization", "offspring"])
def test_late_generation_preserves_budget_failure_without_publishing_candidate(tmp_path, stage):
    now, control = control_fixture()
    calls = []

    def generate(request):
        calls.append(request)
        if stage == "initialization" or request.iteration > 0:
            now[0] = 2
        return draft_for_score(1)

    context = build_context(tmp_path, generate)
    context = replace(context, config=replace(context.config, population_size=1, num_islands=1),
                      remaining_timeout=control.check)
    with pytest.raises(SolveExecutionBudgetExceeded):
        PopulationStrategy(context).run()
    records = CandidateArchive(context.workspace).records()
    assert len(records) == (0 if stage == "initialization" else 1)
    assert len(calls) == (1 if stage == "initialization" else 2)


def test_bundle_execution_and_scoring_use_remainder_without_changing_authority(tmp_path, monkeypatch):
    import famou.candidate_evaluation as evaluation
    import famou.candidate_execution_runner as execution

    context = build_context(tmp_path, lambda _: draft_for_score(1))
    context = replace(context, config=replace(context.config, population_size=1, num_islands=1,
                                              offspring_per_iteration=1),
                      remaining_timeout=lambda stage: 0.7)
    pipeline = context.bundle_pipeline
    pins = pipeline.evaluator.digest(), pipeline.budget, context.config.to_dict()
    observed = []
    original_execution, original_evaluation = execution._bounded_process, evaluation._bounded_process_bytes

    def run(*args, **kwargs):
        observed.append(("execution", kwargs["timeout"]))
        return original_execution(*args, **kwargs)

    def score(*args, **kwargs):
        observed.append(("evaluation", kwargs["timeout"]))
        return original_evaluation(*args, **kwargs)

    monkeypatch.setattr(execution, "_bounded_process", run)
    monkeypatch.setattr(evaluation, "_bounded_process_bytes", score)
    assert PopulationStrategy(context).run().status == "completed"
    assert observed == [("execution", 0.7), ("evaluation", 0.7)] * 2
    assert (pipeline.evaluator.digest(), pipeline.budget, context.config.to_dict()) == pins


def test_late_scoring_cannot_publish_evaluation_or_candidate(tmp_path, monkeypatch):
    import famou.candidate_evaluation as evaluation

    now, control = control_fixture()
    context = build_context(tmp_path, lambda _: draft_for_score(1))
    context = replace(context, remaining_timeout=control.check)
    original = evaluation._bounded_process_bytes

    def score(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] = 2
        return result

    monkeypatch.setattr(evaluation, "_bounded_process_bytes", score)
    with pytest.raises(SolveExecutionBudgetExceeded):
        PopulationStrategy(context).run()
    assert CandidateArchive(context.workspace).records() == []
    assert not list(context.workspace.rglob("evaluation.json"))


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_agent_generation_checks_late_response_before_completed_receipt(tmp_path, outcome):
    now, control = control_fixture()
    adapter = FixtureAgent()
    original = adapter.run

    def run(request):
        result = original(request)
        now[0] = 2
        if outcome == "error":
            raise RuntimeError("runtime timed out")
        return result

    adapter.run = run
    generator = AgentCandidateGenerator(adapter, contract=_contract(), timeout=5)
    generator.set_remaining_timeout(control.check)
    observed = []
    generator.set_observer(lambda kind, payload: observed.append((kind, payload)))
    request = GenerationRequest(iteration=0, parent=None, inspirations=(), archive=(), workspace=tmp_path)
    with pytest.raises(SolveExecutionBudgetExceeded):
        generator(request)
    assert adapter.requests[0].timeout == 1
    assert all(payload.get("reason") != "completed" for _, payload in observed)


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_bundle_agent_checks_late_response_before_completed_receipt(tmp_path, outcome):
    now, control = control_fixture()
    context = build_context(tmp_path)
    adapter = BundleFixtureAgent()
    original = adapter.run

    def run(request):
        result = original(request)
        now[0] = 2
        if outcome == "error":
            raise RuntimeError("runtime timed out")
        return result

    adapter.run = run
    generator = _generator(context, adapter)
    generator.set_remaining_timeout(control.check)
    observed = []
    generator.set_observer(lambda kind, payload: observed.append((kind, payload)))
    request = GenerationRequest(0, None, (), (), context.workspace)
    with pytest.raises(SolveExecutionBudgetExceeded):
        generator(request)
    assert adapter.requests[0].timeout == 1
    assert all(payload.get("reason") != "completed" for _, payload in observed)


@pytest.mark.parametrize("during", ["compiler", "preflight"])
def test_preparation_propagates_solve_budget_as_terminal_authority(tmp_path, monkeypatch, during):
    import famou.evaluator_bundle as bundle

    controller, parent, contract, _runtime = _fixture(tmp_path)
    now, control = control_fixture()
    if during == "compiler":
        original = bundle._run_isolated

        def run(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 2
            return result

        monkeypatch.setattr(bundle, "_run_isolated", run)
    else:
        import famou.candidate_execution_runner as runner

        original = runner._bounded_process_bytes

        def run(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 2
            return result

        monkeypatch.setattr(runner, "_bounded_process_bytes", run)
    with pytest.raises(SolveExecutionBudgetExceeded):
        prepare_automatic_solve_bundle(controller, parent.id, contract, timeout_seconds=3,
                                       solve_control=control)
    events = controller.store.list_events(parent.id)
    assert not any(item["type"] == "bundle_profile_prepared" for item in events)
    assert not any(item["type"] == "bundle_preparation_failed" for item in events)
