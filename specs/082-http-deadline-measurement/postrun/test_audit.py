"""Rebind the pinned two-slot fixtures; add only Feature 082 wrapper-specific regressions."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import AggregateUsage, WorkflowController, WorkflowManifest


def load(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("test_postrun082_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit, report = load("audit"), load("render_report")
adapter, _legacy = audit.dependencies()
prior_tests = adapter.load_previous_postrun("test_audit")
prior_tests.audit, prior_tests.report = audit, report
_prior_report_fixture = prior_tests.report_fixture


def report_fixture():
    fixture = _prior_report_fixture()
    fixture.update(kind="feature082_postrun_audit", implementation_commit=adapter.IMPLEMENTATION)
    fixture["slots"] = [{"index": index} for index in (1, 2)]
    return fixture


prior_tests.report_fixture = report_fixture
# Exercise the original parameterized registration, frozen-byte/runtime, native-stage, fixed-two-slot,
# completion, extra-attempt and null/>1 report gates against these wrappers, without copying tests.
globals().update({name: value for name, value in vars(prior_tests).items()
                  if name.startswith("test_") or name in {"top_level", "registration"}})


def test_current_campaign_source_and_analysis_identity_are_bound(top_level):
    result = prior_tests.inspect(top_level)
    assert result["kind"] == "feature082_postrun_audit"
    assert result["implementation_commit"] == "e36b103fd6fc4a64304d16ae446e0383dab0a8a8"
    assert result["analysis_script_sha256"] == hashlib.sha256(Path(audit.__file__).read_bytes()).hexdigest()
    assert result["summary"]["planned_attempts"] == 2
    assert all(slot["terminal_diagnostic"]["status"] == "unavailable" for slot in result["slots"])
    assert result["timing"]["exact_master_duration_available"] is False
    assert {"historical_attempts_excluded", "plan_or_build_evidence_does_not_establish_validity"} <= set(result["limitations"])


@pytest.mark.parametrize("prior", ["074-corrected-staged-measurement", "076-public-plan-handoff-measurement"])
def test_prior_campaign_cannot_be_audited_as_current(monkeypatch, prior):
    def must_not_verify(*args):
        raise AssertionError("old campaign reached current registration validator")

    monkeypatch.setattr(audit, "verify_registration", must_not_verify)
    old = adapter.REPO / "specs" / prior / "measurement/manifest.json"
    with pytest.raises(ValueError, match="wrong.*campaign"):
        audit.audit_registered_campaign(old, adapter.CAMPAIGN)


@pytest.mark.parametrize("field,value", [
    ("kind", "feature076_postrun_audit"), ("implementation_commit", "0" * 40),
])
def test_report_rejects_prior_or_unbound_audit(field, value):
    fixture = report_fixture()
    fixture[field] = value
    with pytest.raises(ValueError, match="audit identity"):
        report.render_report(fixture)


def test_current_report_title_preserves_prior_score_and_denominator_contract():
    fixture = report_fixture()
    prior_tests.accept_first(fixture)
    text = report.render_report(fixture)
    assert text.startswith("# Lunar Agent HTTP deadline评测（Feature 082）\n")
    assert "1.0185 | 1.0185" in text and "null | null | null" in text
    assert "固定分母2" in text and "不声称修复因果效果" in text


def test_postrun_loaders_do_not_publish_global_dependency_aliases():
    names = ("prepare", "worker", "campaign", "audit", "adapter", "dry_run")
    before = {name: sys.modules.get(name) for name in names}
    for name in ("audit", "render_report", "test_audit"):
        assert adapter.load_previous_postrun(name).__file__
    assert {name: sys.modules.get(name) for name in names} == before


@pytest.mark.parametrize("name", ["audit", "render_report", "test_audit"])
def test_each_reused_postrun_helper_is_pinned_before_evaluation(monkeypatch, name):
    relative = "postrun/" + name + ".py"
    key = (adapter.PREVIOUS_ROOT / relative).relative_to(adapter.REPO).as_posix()
    assert adapter.HELPER_FILES[key] == adapter.PREVIOUS_FILES[relative]
    monkeypatch.setitem(adapter.PREVIOUS_FILES, relative, "0" * 64)
    with pytest.raises(ValueError, match="pinned measurement helper changed"):
        adapter.load_previous_postrun(name)


def test_public_scorer_plan_and_completed_build_are_audited_without_recovery(tmp_path, monkeypatch):
    campaign, case = tmp_path / "campaign", "sheet_metal_nesting"
    workspace = campaign / f"slots/001/trial/cases/{case}/runs/001/attempts/001/subject"
    manifest = WorkflowManifest(
        run_id="public-plan-fixture", attempt_id="slot-001-attempt-001", source_sha256="a" * 64,
        suite_key="fixture", case_key=case, request_sha256="b" * 64, model_profile_sha256="c" * 64,
        ceilings={"max_wall_seconds": 5400, "max_tool_steps": 200,
                  "max_total_tokens": 8_000_000, "max_cost_micros": None},
    )
    config = StagedWorkflowConfig(manifest, StagePolicy(**adapter.POLICIES["master_1200"]))
    slot = {"index": 1, "arm": "S", "budget_arm": "master_1200", "case_key": case,
            "workflow_config": config.to_dict()}
    controller = WorkflowController(workspace, manifest)
    (controller.workflow / "config.json").write_text(json.dumps(config.to_dict()))
    paths = ["scorer.py", "baseline_solution.py", "_agent_summary.md"]
    controller.write_master(["Implement the public objective scorer and combined_score."], paths)
    stage_validator, legacy = adapter.load_prior_postrun(), adapter.load_legacy("postrun")
    planned = stage_validator.stage_evidence(slot, campaign, legacy.Evidence(tmp_path), legacy)
    assert planned["plan_record_valid"] is True and planned["build_entered_observed"] is False
    controller.transition("build_running")
    for name in paths:
        (workspace / name).write_text("# Synthetic fixture; never executed.\n")
    for name in ("session-transcript.jsonl", "transcript-000001.jsonl"):
        (controller.workflow / name).write_text('{}\n')
    controller.checkpoint(
        stage="build_ready", declared_paths=paths, usage=AggregateUsage(True, 1, 1, 2, None, 1, 1),
        transcript=Path("workflow/transcript-000001.jsonl"),
    )
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}

    def refuse(*args, **kwargs):
        raise AssertionError("observation attempted controller construction or mutation")

    for name in ("__init__", "_write_new", "_write_replace", "transition"):
        monkeypatch.setattr(WorkflowController, name, refuse)
    completed = stage_validator.stage_evidence(
        slot, campaign, legacy.Evidence(tmp_path), legacy, subject_accepted=True,
    )
    assert completed["plan_record_valid"] is completed["build_entered_observed"] is True
    assert completed["workflow_stage"] == "build_ready" and completed["master_duration_seconds"] is None
    assert not {"validity_score", "overall_score", "quality_score"}.intersection(completed)
    assert not (workspace / "receipt.json").exists()
    assert {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()} == before


@pytest.fixture
def terminal(tmp_path):
    from types import SimpleNamespace

    campaign = tmp_path / 'campaign'
    slot = {'index': 1, 'case_key': 'sheet_metal_nesting'}
    root = campaign / 'slots/001'
    attempt = root / 'trial/cases/sheet_metal_nesting/runs/001/attempts/001'
    subject = attempt / 'subject'
    subject.mkdir(parents=True)
    request = {'mode': 'normal', 'run_index': 1, 'receipt_path': 'receipt.json'}
    request_path = subject / 'request.json'
    request_path.write_text(json.dumps(request))
    slot['request_sha256'] = hashlib.sha256(request_path.read_bytes()).hexdigest()
    payload = {
        'schema_version': '4', 'kind': 'subject_failure', 'mode': 'normal',
        'request_sha256': slot['request_sha256'], 'run_index': 1, 'round_index': None,
        'stage': 'model', 'code': 'timeout', 'model_turns': 2, 'tool_steps': 3,
        'http_status': None, 'model_failure': {'reason': 'transport_timeout', 'response_status': None},
        'request_observation': {'phase': 'open_response', 'elapsed_ms': 120001, 'request_timeout_ms': 120000},
    }
    original, collected = subject / 'receipt.failure.json', attempt / 'diagnostics/subject-failure.json'
    collected.parent.mkdir()
    for path in (original, collected):
        path.write_text(json.dumps(payload))
    record = {'status': 'failed', 'ready': False, 'attempt': 'cases/sheet_metal_nesting/runs/001/attempts/001'}
    record_path = attempt.parent.parent / 'record.json'
    record_path.write_text(json.dumps(record))
    row = {'process_terminated': True, 'report_sha256': 'a' * 64,
           'subject_receipt_accepted': False, 'harness_receipt_accepted': False}
    calls = []

    def read_accepted(manifest, selected, digest):
        calls.append((manifest, selected, digest))
        return record, root, {}

    return SimpleNamespace(campaign=campaign, slot=slot, row=row, legacy=_legacy,
                           evidence=_legacy.Evidence(tmp_path), reader=SimpleNamespace(read_accepted_run=read_accepted),
                           payload=payload, original=original, collected=collected, record=record,
                           record_path=record_path, request_path=request_path, calls=calls)


def diagnostic(t):
    return audit.terminal_diagnostic(t.slot, t.campaign, {}, 'd' * 64, t.row, t.evidence, t.reader, t.legacy)


@pytest.mark.parametrize('version', ['1', '2', '3', '4'])
def test_terminal_projection_requires_native_failed_record_and_dual_bound_evidence(terminal, version):
    t = terminal
    t.payload['schema_version'] = version
    if version != '4':
        t.payload.pop('request_observation')
    if version in {'1', '2'}:
        t.payload.pop('model_failure')
    if version == '2':
        t.payload.update(stage='runtime', code='budget_exceeded', budget={
            'limit': 'max_total_tokens', 'state': 'exhausted', 'maximum': 100,
            'accepted_usage': None, 'observed_usage': None, 'trigger_recorded': True,
            'usage_completeness': 'partial',
        })
    for path in (t.original, t.collected):
        path.write_text(json.dumps(t.payload))
    result = diagnostic(t)
    assert result['status'] == 'validated'
    assert result['payload']['schema_version'] == version
    assert result['payload']['stage'] == t.payload['stage'] and result['payload']['code'] == t.payload['code']
    assert ('request_observation' in result['payload']) is (version == '4')
    assert len(t.calls) == 1
    assert result['evidence_sha256'] == {
        path.relative_to(t.evidence.repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (t.original, t.collected, t.request_path, t.record_path)}
    assert not {'usage', 'cost_micros', 'validity_score', 'overall_score', 'quality_score'} & result['payload'].keys()
    t.evidence.unchanged()


@pytest.mark.parametrize('change', ['identity', 'mode', 'run', 'round', 'extra', 'bool', 'phase', 'copy', 'missing',
                                     'oversize', 'json', 'nested'])
def test_invalid_terminal_diagnostics_degrade_without_scores_or_exception_text(terminal, change):
    t = terminal
    if change == 'missing':
        t.collected.unlink()
    elif change in {'oversize', 'json', 'nested'}:
        t.original.write_text({'oversize': 'x' * 4097, 'json': '{', 'nested': '[' * 1500 + ']' * 1500}[change])
    else:
        field, value = {
            'identity': ('request_sha256', '0' * 64), 'mode': ('mode', 'deep_evolution'),
            'run': ('run_index', 2), 'round': ('round_index', 1), 'extra': ('secret', 'PRIVATE'),
            'bool': ('model_turns', True), 'phase': ('request_observation', {
                'phase': 'private phase', 'elapsed_ms': 1, 'request_timeout_ms': 100}),
            'copy': ('model_turns', 4),
        }[change]
        t.payload[field] = value
        t.original.write_text(json.dumps(t.payload))
        if change != 'copy':
            t.collected.write_text(json.dumps(t.payload))
    result = diagnostic(t)
    assert result['status'] in {'unavailable', 'rejected'} and result['payload'] is None
    assert 'PRIVATE' not in json.dumps(result) and 'private phase' not in json.dumps(result)
    assert not any(t.row[name] for name in ('subject_receipt_accepted', 'harness_receipt_accepted'))


@pytest.mark.parametrize('change', ['running', 'no_report', 'completed', 'ready', 'subject_accepted'])
def test_diagnostic_never_substitutes_for_terminal_native_failure(terminal, change):
    t = terminal
    if change == 'running':
        t.row['process_terminated'] = False
    elif change == 'no_report':
        t.row['report_sha256'] = None
    elif change == 'completed':
        t.record['status'] = 'completed'
    elif change == 'ready':
        t.record['ready'] = True
    else:
        t.row['subject_receipt_accepted'] = True
    assert diagnostic(t)['status'] == 'unavailable'


@pytest.mark.parametrize('change', ['symlink', 'during_observation'])
def test_diagnostic_evidence_path_or_byte_drift_still_rejects_whole_audit(terminal, change):
    t = terminal
    if change == 'symlink':
        t.original.unlink()
        t.original.symlink_to(t.collected)
        with pytest.raises(ValueError, match='linked'):
            diagnostic(t)
    else:
        assert diagnostic(t)['status'] == 'validated'
        t.collected.write_text('{}')
        with pytest.raises(ValueError, match='changed'):
            t.evidence.unchanged()


def test_report_renders_only_validated_safe_diagnostics(terminal):
    fixture = report_fixture()
    projected = diagnostic(terminal)
    fixture['slots'][0]['terminal_diagnostic'] = projected
    text = report.render_report(fixture)
    assert 'transport_timeout' in text and 'open_response' in text
    assert '120001' in text and '120000' in text
    assert '诊断不授予' in text


@pytest.mark.parametrize('relative,raw', [
    ('subject/receipt.failure.json', b'{'),
    ('diagnostics/subject-failure.json', b'{}'),
    ('subject/request.json', b'{}'),
])
def test_transient_diagnostic_reads_must_match_tracked_bytes_before_tolerant_parse(terminal, monkeypatch, relative, raw):
    import famou.subject_diagnostics as native

    original = native.read_bounded_file

    def altered(root, name, maximum):
        return raw if name == relative else original(root, name, maximum)

    monkeypatch.setattr(native, 'read_bounded_file', altered)
    with pytest.raises(ValueError, match='changed'):
        diagnostic(terminal)


@pytest.mark.parametrize('kind', ['timeout', 'http_error'])
def test_native_v4_subject_failure_and_collection_never_authorize_harness(tmp_path, kind):
    import subprocess
    from types import SimpleNamespace
    from urllib.error import HTTPError

    from test_effect_trial import _fixture

    from famou.effect_adapters import EffectAdapterError, run_subject_adapter
    from famou.effect_trial import EffectTrialConfig, EffectTrialRunner
    from famou.runtime import ModelRequestFailure, ModelRequestObservation

    suite, baseline, public, subject, harness = _fixture(tmp_path)
    baseline_data = json.loads(baseline.read_bytes())
    baseline_data['model']['requested'] = 'glm-5.2'
    baseline.write_text(json.dumps(baseline_data))
    campaign, root = tmp_path / 'campaign', tmp_path / 'campaign/slots/001'
    error = ModelRequestFailure('PRIVATE-MODEL-ERROR', 'transport_timeout' if kind == 'timeout' else 'http_error',
                                None if kind == 'timeout' else 429)
    error.observation = ModelRequestObservation('open_response' if kind == 'timeout' else 'read_http_error_body',
                                                101, 100)
    error.__cause__ = TimeoutError('PRIVATE') if kind == 'timeout' else HTTPError('http://fixture.invalid', 429, 'PRIVATE', {}, None)
    invocations = []

    class Model:
        model = 'glm-5.2'

        def complete(self, *args, **kwargs):
            raise error

    def executor(command, *, cwd, env, timeout):
        invocations.append(cwd.name)
        assert cwd.name == 'subject'
        with pytest.raises(EffectAdapterError):
            run_subject_adapter(Path(command[-1]), model_runtime=Model(), max_steps=8)
        return subprocess.CompletedProcess(command, 2)

    runner = EffectTrialRunner(suite, baseline, root / 'trial', case_sources={'fixture_case': public},
                               config=EffectTrialConfig(runs_per_case=1, timeout_seconds=10,
                                                        requested_model='glm-5.2', subject_command=subject,
                                                        harness_command=harness), process_executor=executor)
    record = runner.run().to_dict()['cases'][0]['runs'][0]
    runner._validate_record(json.loads((root / 'trial/cases/fixture_case/runs/001/record.json').read_bytes()),
                            runner.suite.cases[0], 1)
    attempt = root / 'trial' / record['attempt']
    slot = {'index': 1, 'case_key': 'fixture_case',
            'request_sha256': hashlib.sha256((attempt / 'subject/request.json').read_bytes()).hexdigest()}
    row = {'process_terminated': True, 'report_sha256': 'a' * 64,
           'subject_receipt_accepted': False, 'harness_receipt_accepted': False}
    result = audit.terminal_diagnostic(slot, campaign, {}, 'd' * 64, row, _legacy.Evidence(tmp_path),
                                       SimpleNamespace(read_accepted_run=lambda *args: (record, root, {})), _legacy)
    assert result['status'] == 'validated' and result['payload']['schema_version'] == '4'
    assert result['payload']['code'] == ('timeout' if kind == 'timeout' else 'model_http_failed')
    assert invocations == ['subject'] and record['error_code'] == 'process_nonzero_exit'
    assert all(record[key] is None for key in ('usage', 'cost_micros', 'validity_score', 'overall_score'))
    assert not record['ready'] and not (attempt / 'subject/receipt.json').exists()
    assert not (attempt / 'harness').exists() and 'PRIVATE' not in json.dumps(result)


def test_final_report_requires_both_rows_terminated_and_preserves_unknown_scores():
    fixture = report_fixture()
    for row in fixture['summary']['slots']:
        row.update(started=True, process_terminated=True, status='terminated_without_accepted_report')
    fixture['summary']['budget_arms']['master_1200'].update(started=2, terminated=2)
    fixture['summary']['all_slots_terminated'] = True
    fixture.update(complete=True, final_acceptance=True)
    text = report.render_report(fixture)
    scores = text.split('\n## 终止请求诊断', 1)[0]
    assert '两个尝试已终止，结果审计通过' in text and '已观察有效解0' in text
    assert scores.count('null | null | null') == 2 and '不是最终失败率' not in text
