"""Local-only measurement projection, one-start, wave barrier, and timeout checks."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_worker069 import scaffold

from famou.effect_trial import _canonical_bytes

SCRIPTS = Path(__file__).resolve().parents[1] / 'specs/069-webagent-normal-workflow/measurement'


@pytest.fixture
def campaign_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('offline_campaign069', SCRIPTS / 'campaign.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wave_two_waits_for_both_wave_one_slots(campaign_module, monkeypatch):
    lock = threading.Lock()
    completed = set()
    calls = []

    def run(slot, env, digest):
        index = slot['index']
        with lock:
            if index > 2:
                assert {1, 2} <= completed
            calls.append(index)
        time.sleep(0.02 if index == 1 else 0.001)
        with lock:
            completed.add(index)
        return index

    monkeypatch.setattr(campaign_module, 'run_slot', run)
    result = campaign_module.execute_waves(
        {'execution': {'waves': [[1, 2], [3, 4]]},
         'slots': [{'index': index} for index in range(1, 5)]}, {}, 'a' * 64,
    )
    assert result == [1, 2, 3, 4] and sorted(calls) == [1, 2, 3, 4]


def test_slot_marker_prevents_second_dispatch(tmp_path, campaign_module, monkeypatch):
    monkeypatch.setattr(campaign_module, 'CAMPAIGN', tmp_path.resolve())
    calls = []
    monkeypatch.setattr(campaign_module, 'execute_slot', lambda *a, **kw: calls.append(kw) or 0)
    campaign_module.run_slot({'index': 1}, {}, 'a' * 64)
    with pytest.raises(FileExistsError):
        campaign_module.run_slot({'index': 1}, {}, 'a' * 64)
    assert len(calls) == 1 and calls[0]['timeout'] == 9300


def test_outer_timeout_stops_local_process_group(tmp_path, campaign_module):
    pidfile = tmp_path / 'child.pid'
    script = tmp_path / 'parent.py'
    script.write_text(
        "import subprocess,sys,time\n"
        "from pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "Path(sys.argv[1]).write_text(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        campaign_module.execute_slot(
            [sys.executable, str(script), str(pidfile)], cwd=tmp_path,
            env=campaign_module.BASE_ENV, timeout=1,
        )
    pid = int(pidfile.read_text())
    # Reparented child may briefly be a zombie; either state means execution has stopped.
    for _ in range(20):
        status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True,
                                text=True, env=campaign_module.BASE_ENV, check=False).stdout.strip()
        if not status or status.startswith('Z'):
            break
        time.sleep(0.02)
    assert not status or status.startswith('Z')


def native_evidence(tmp_path, module, monkeypatch, *, extraction='completed', failure=False):
    import worker
    campaign, manifest, slot, configured = scaffold(tmp_path, worker, monkeypatch)
    monkeypatch.setattr(module, 'REPO', tmp_path.resolve())
    monkeypatch.setattr(module, 'CAMPAIGN', campaign)
    monkeypatch.setattr(module, 'HERE', campaign)
    manifest['slots'] = [dict(slot, index=index, arm='M' if index in (1, 4) else 'S')
                         for index in range(1, 5)]
    module.write_new(campaign / 'manifest.json', manifest)
    digest = module.sha(campaign / 'manifest.json')
    (campaign / 'manifest.sha256').write_text(digest + '\n')
    root = campaign / 'slots/001'

    def process(command, *, cwd, env, timeout):
        request = module.read(cwd / 'request.json')
        if cwd.name == 'subject':
            (cwd / 'candidate.json').write_text('{}')
            if failure:
                return subprocess.CompletedProcess(command, 2)
            receipt = {
                'schema_version': '1', 'mode': 'normal', 'status': 'completed',
                'requested_model': 'glm-5.2', 'effective_model': 'glm-5.2',
                'model_evidence': 'provider_observed', 'interaction_turns': 2,
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
                'model_profile_sha256': request['model_profile_sha256'], 'cost_micros': None,
            }
        else:
            module.write_new(root / 'harness-started.json', {
                'index': 1, 'manifest_sha256': digest, 'stage': 'harness',
            })
            receipt = {
                'schema_version': '1', 'status': 'completed',
                **{key: request[key] for key in ('benchmark', 'evaluation_profile', 'case', 'harness')},
                'extraction_status': extraction, 'validity_score': 1 if extraction == 'completed' else 0,
                'overall_score': 1.2 if extraction == 'completed' else 0,
                'quality_score': None, 'detail_metrics': {},
            }
        worker.write_new(cwd / 'receipt.json', receipt)
        return subprocess.CompletedProcess(command, 0)

    runner = worker.build_runner(manifest, campaign, slot, configured, process_executor=process)
    runner.run()
    record = module.read(root / 'trial/cases/fixture_case/runs/001/record.json')
    outcome = {
        'index': 1, 'arm': 'M', 'case_key': 'fixture_case', 'manifest_sha256': digest,
        'status': 'terminated', 'record_status': record['status'], 'worker_returncode': 0,
        'record_sha256': hashlib.sha256(_canonical_bytes(record)).hexdigest(),
        'report_sha256': module.sha(root / 'trial/report.json'),
    }
    module.write_new(root / 'worker-started.json', {'index': 1, 'manifest_sha256': digest})
    module.write_new(root / 'outcome.json', outcome)
    module.write_new(root / 'worker-terminated.json', {
        'index': 1, 'manifest_sha256': digest, 'returncode': 0,
        'outcome_sha256': module.sha(root / 'outcome.json'),
    })
    for phase in ('started', 'terminated'):
        module.write_new(campaign / f'slot-001-{phase}.json', {'index': 1, 'manifest_sha256': digest,
                                                                       'exit_code': 0, 'failure': None})
    return campaign, root


@pytest.mark.parametrize('kind', ['success', 'failed_extraction', 'failed_subject'])
def test_summary_fixed_denominator_and_null_scores(tmp_path, campaign_module, monkeypatch, kind):
    native_evidence(tmp_path, campaign_module, monkeypatch,
                    extraction='failed' if kind == 'failed_extraction' else 'completed',
                    failure=kind == 'failed_subject')
    summary = campaign_module.summarize()
    row = summary['slots'][0]
    assert summary['planned_attempts'] == 4 and summary['arms']['M']['planned'] == 2
    assert not summary['all_slots_terminated'] and summary['pooled_quality_mean'] is None
    assert all(r['overall_score'] is None for r in summary['slots'][1:])
    assert row['overall_score'] == (1.2 if kind == 'success' else None)
    assert summary['arms']['M']['valid_solution_rate'] == (0.5 if kind == 'success' else 0)
    assert row['subject_receipt_accepted'] == (kind != 'failed_subject')


@pytest.mark.parametrize('changed', ['report', 'record', 'state', 'outcome', 'attempt'])
def test_summary_rejects_broken_native_digest_chain(tmp_path, campaign_module, monkeypatch, changed):
    _, root = native_evidence(tmp_path, campaign_module, monkeypatch)
    paths = {
        'report': root / 'trial/report.json',
        'record': root / 'trial/cases/fixture_case/runs/001/record.json',
        'state': root / 'trial/control/state.json', 'outcome': root / 'outcome.json',
    }
    if changed == 'attempt':
        (root / 'trial/cases/fixture_case/runs/001/attempts/002').mkdir()
    else:
        path = paths[changed]
        value = json.loads(path.read_text())
        if changed == 'state':
            value['records']['fixture_case/001'] = 'b' * 64
        else:
            value['tampered'] = True
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        campaign_module.summarize()


@pytest.mark.parametrize('missing', ['slot', 'worker', 'exit'])
def test_summary_requires_start_and_consistent_exit(tmp_path, campaign_module, monkeypatch, missing):
    campaign, root = native_evidence(tmp_path, campaign_module, monkeypatch)
    if missing == 'slot':
        (campaign / 'slot-001-started.json').unlink()
    elif missing == 'worker':
        (root / 'worker-started.json').unlink()
    else:
        path = campaign / 'slot-001-terminated.json'
        value = json.loads(path.read_text())
        value['exit_code'] = 124
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        campaign_module.summarize()


def test_summary_never_restores_record_backup(tmp_path, campaign_module, monkeypatch):
    _, root = native_evidence(tmp_path, campaign_module, monkeypatch)
    path = root / 'trial/cases/fixture_case/runs/001/record.json'
    backup = path.with_name('record.previous.json')
    original = path.read_bytes()
    backup.write_bytes(original)
    path.write_text('{}')
    with pytest.raises(ValueError):
        campaign_module.summarize()
    assert path.read_text() == '{}' and backup.read_bytes() == original
