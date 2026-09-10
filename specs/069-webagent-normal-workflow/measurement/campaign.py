"""One-shot fixed-wave dispatch; no keys are written to campaign artifacts or argv."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from prepare import CAMPAIGN, HERE, REPO, read, require, sha, write_new
from worker import HARNESS_ENV_NAMES, SUBJECT_ENV_NAMES, commands, confined

from famou.effect_trial import EffectTrialConfig, EffectTrialRunner, _canonical_bytes

BASE_ENV = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}


def execute_slot(command, *, cwd, env, timeout):
    child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
    try:
        return child.wait(timeout=timeout)
    except BaseException:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        raise


def run_slot(slot, environment, manifest_sha):
    index = slot['index']
    write_new(CAMPAIGN / f'slot-{index:03d}-started.json', {
        'index': index, 'manifest_sha256': manifest_sha, 'started_unix_seconds': time.time(),
    })
    started = time.monotonic()
    exit_code, failure = None, None
    try:
        exit_code = execute_slot(
            [str(REPO / '.venv/bin/python'), str(HERE / 'worker.py'),
             '--manifest', str(HERE / 'manifest.json'), '--campaign', str(CAMPAIGN),
             '--slot', str(index)],
            cwd=REPO, env=environment, timeout=9300,
        )
    except (OSError, subprocess.TimeoutExpired):
        failure = 'slot_timeout_or_launch_failure'
    result = {'index': index, 'manifest_sha256': manifest_sha, 'exit_code': exit_code,
              'failure': failure, 'elapsed_seconds': round(time.monotonic() - started, 3)}
    write_new(CAMPAIGN / f'slot-{index:03d}-terminated.json', result)
    print(json.dumps(result), flush=True)
    return result


def read_accepted_run(manifest, slot, manifest_sha):
    """Offline native record validation plus worker termination/report digest linkage."""
    root = confined(CAMPAIGN, f"slots/{slot['index']:03d}")
    outcome = read(root / 'outcome.json')
    for key in ('index', 'arm', 'case_key'):
        require(outcome[key] == slot[key], 'worker outcome identity mismatch')
    require(outcome['manifest_sha256'] == manifest_sha)
    began = read(confined(root, 'worker-started.json'))
    require(began['index'] == slot['index'] and began['manifest_sha256'] == manifest_sha)
    ended = read(confined(root, 'worker-terminated.json'))
    require(ended['index'] == slot['index'] and ended['manifest_sha256'] == manifest_sha)
    require(ended['outcome_sha256'] == sha(root / 'outcome.json'))
    require(ended['returncode'] == outcome['worker_returncode'] == 0)
    report_path = confined(root, 'trial/report.json')
    require(outcome['status'] == 'terminated' and sha(report_path) == outcome['report_sha256'])
    subject, harness = commands(manifest, CAMPAIGN, slot)
    # Environment names, not values, are the native identity. This reader cannot dispatch.
    config = EffectTrialConfig(
        runs_per_case=1, timeout_seconds=5400, requested_model='glm-5.2',
        subject_command=subject, harness_command=harness,
        subject_environment=dict.fromkeys((*SUBJECT_ENV_NAMES, 'PYTHONDONTWRITEBYTECODE'), ''),
        harness_environment=dict.fromkeys((*HARNESS_ENV_NAMES, 'PYTHONDONTWRITEBYTECODE'), ''),
        model_profile_sha256=manifest['profile_sha256'],
        subject_model_profile_path=CAMPAIGN / 'inputs/profile.json',
    )

    def no_dispatch(*args, **kwargs):
        raise AssertionError('summary cannot dispatch')

    reader = EffectTrialRunner(
        CAMPAIGN / 'inputs' / f"{slot['case_key']}-suite.json",
        CAMPAIGN / 'inputs' / f"{slot['case_key']}-baseline.json", root / 'trial',
        case_sources={slot['case_key']: REPO / manifest['cases'][slot['case_key']]['public_root_rel']},
        config=config, resume=True, process_executor=no_dispatch,
    )
    state = reader._prepare_state()  # resume=True is a read-only identity/control-copy check.
    case = reader.suite.cases[0]
    record = read(confined(root, f'trial/cases/{case.key}/runs/001/record.json'))
    record_sha = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    require(record_sha == outcome['record_sha256']
            and state['records'] == {case.key + '/001': record_sha})
    record = reader._validate_record(record, case, 1)
    require(record['status'] == outcome['record_status'])
    require(record['attempt'] == f'cases/{case.key}/runs/001/attempts/001')
    require(len(list((root / f'trial/cases/{case.key}/runs/001/attempts').iterdir())) == 1)
    report = read(report_path)
    require(report['config'] == config.safe_dict())
    require(report['suite_sha256'] == reader.suite_sha256
            and report['baseline_sha256'] == reader.baseline_sha256)
    require(report['cases'] == [reader._case_report(case, [record])], 'report projection mismatch')
    return report['cases'][0]['runs'][0], root, outcome


def summarize():
    """Read only accepted runner records; extraction-failure placeholders remain unscored."""
    manifest = read(HERE / 'manifest.json')
    manifest_sha = sha(HERE / 'manifest.json')
    require(manifest_sha == (HERE / 'manifest.sha256').read_text().strip())
    require((CAMPAIGN / 'manifest.json').read_bytes() == (HERE / 'manifest.json').read_bytes())
    rows = []
    for slot in manifest['slots']:
        root = confined(CAMPAIGN, f"slots/{slot['index']:03d}")
        row = {k: slot[k] for k in ('index', 'arm', 'case_key')}
        row.update(status='not_started', started=False, process_terminated=False,
                   subject_receipt_accepted=False, harness_receipt_accepted=False,
                   validity_score=None, overall_score=None, quality_score=None,
                   usage=None, cost_micros=None, interaction_turns=None, report_sha256=None,
                   resume_used=None, elapsed_ms=None, extraction_status=None, error_code=None)
        for phase in ('started', 'terminated'):
            path = confined(CAMPAIGN, f"slot-{slot['index']:03d}-{phase}.json")
            if path.is_file():
                marker = read(path)
                require(marker['index'] == slot['index'] and marker['manifest_sha256'] == manifest_sha)
                row['started' if phase == 'started' else 'process_terminated'] = True
        if row['started']:
            row['status'] = 'started_unresolved'
        if row['process_terminated']:
            require(row['started'], 'terminated slot lacks start evidence')
            row['status'] = 'terminated_without_accepted_report'
        # outcome is published after the native record/state/report transaction finishes.
        if (root / 'worker-terminated.json').is_file() and (root / 'outcome.json').is_file():
            outcome = read(root / 'outcome.json')
            if outcome.get('report_sha256') is not None:
                require(row['started'], 'accepted record lacks outer start evidence')
                run, root, outcome = read_accepted_run(manifest, slot, manifest_sha)
                if row['process_terminated']:
                    ended = read(CAMPAIGN / f"slot-{slot['index']:03d}-terminated.json")
                    require(ended['exit_code'] == outcome['worker_returncode'] and ended['failure'] is None)
                row.update(status=run['status'], report_sha256=outcome['report_sha256'],
                           record_sha256=outcome['record_sha256'], elapsed_ms=run['elapsed_ms'])
                harness_start = confined(root, 'harness-started.json')
                if harness_start.is_file():
                    marker = read(harness_start)
                    require(marker['index'] == slot['index'] and marker['manifest_sha256'] == manifest_sha
                            and marker['stage'] == 'harness')
                    row['subject_receipt_accepted'] = True
                row['harness_receipt_accepted'] = run['ready']
                if run['ready']:
                    require(row['subject_receipt_accepted'], 'ready run lacks native harness dispatch')
                    for key in ('usage', 'cost_micros', 'interaction_turns'):
                        row[key] = run[key]
                    if run['extraction_status'] == 'completed':
                        for key in ('validity_score', 'overall_score', 'quality_score'):
                            row[key] = run[key]
                row['extraction_status'] = run['extraction_status']
                row['error_code'] = run['error_code']
                workflow = confined(root, 'trial/' + run['attempt'] + '/subject/workflow/state.json')
                if workflow.is_file():
                    row['workflow_state_sha256'] = sha(workflow)
                    row['resume_used'] = read(workflow).get('resume_used')
        rows.append(row)
    arms = {}
    for arm in ('M', 'S'):
        selected = [row for row in rows if row['arm'] == arm]
        require(len(selected) == 2)
        valid = sum(row['harness_receipt_accepted'] and row['validity_score'] is not None
                    and row['validity_score'] > 0 and row['overall_score'] is not None
                    for row in selected)
        arms[arm] = {'planned': 2, 'started': sum(row['started'] for row in selected),
                     'terminated': sum(row['process_terminated'] for row in selected),
                     'valid': valid, 'valid_solution_rate': valid / 2,
                     'subject_receipts': sum(row['subject_receipt_accepted'] for row in selected),
                     'accepted_harness_receipts': sum(row['harness_receipt_accepted'] for row in selected)}
    return {'schema_version': '1', 'kind': 'staged_workflow_measurement',
            'manifest_sha256': manifest_sha, 'planned_attempts': 4,
            'all_slots_terminated': all(row['process_terminated'] for row in rows),
            'slots': rows, 'arms': arms, 'pooled_quality_mean': None,
            'conclusion_eligibility': 'descriptive_only'}


def execute_waves(manifest, environment, manifest_sha):
    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for wave in manifest['execution']['waves']:
            futures = [pool.submit(run_slot, next(s for s in manifest['slots'] if s['index'] == index),
                                   environment, manifest_sha) for index in wave]
            outcomes.extend(future.result() for future in futures)
    return outcomes


def launch():
    from audit import audit
    manifest_path = HERE / 'manifest.json'
    manifest = read(manifest_path)
    require(audit(manifest_path, CAMPAIGN)["passed"] is True)
    manifest_sha = sha(manifest_path)
    # The reviewed registration and reports must already be in git before any paid request.
    for name in ('manifest.json', 'prelaunch-audit.json', 'dry-run.json'):
        file = HERE / name
        committed = subprocess.check_output(['git', 'show', f"HEAD:{file.relative_to(REPO).as_posix()}"], cwd=REPO)
        require(committed == file.read_bytes(), 'commit the final registration/audit/dry-run first')
    audited = read(HERE / 'prelaunch-audit.json')
    require(audited['manifest_sha256'] == manifest_sha and audited['passed'] is True)
    dry = read(HERE / 'dry-run.json')
    require(dry['manifest_sha256'] == manifest_sha and dry['passed'] is True and dry['model_calls'] == 0)
    loader = REPO / '.lunar/real-eval-20260908/ccswitch.py'
    spec = importlib.util.spec_from_file_location('measurement_ccswitch', loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    configured = module.load_environment()  # One snapshot shared by all four subjects/extractors.
    require(configured['ANTHROPIC_MODEL'] == 'glm-5.2')
    for key, digest in manifest['endpoints'].items():
        require(hashlib.sha256(configured[key].encode()).hexdigest() == digest, 'provider endpoint changed')
    allowed = (*SUBJECT_ENV_NAMES, *HARNESS_ENV_NAMES)
    require(all(isinstance(configured.get(key), str) and configured[key] for key in allowed))
    environment = {**BASE_ENV, **{key: configured[key] for key in allowed}}
    write_new(CAMPAIGN / 'started.json', {
        'campaign_id': manifest['campaign_id'], 'manifest_sha256': manifest_sha,
        'registration_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'started_unix_seconds': time.time(), 'planned_attempts': 4, 'concurrency': 2,
    })
    outcomes = execute_waves(manifest, environment, manifest_sha)
    write_new(CAMPAIGN / 'terminated.json', {
        'manifest_sha256': manifest_sha, 'terminated_unix_seconds': time.time(), 'slots': outcomes,
    })
    write_new(CAMPAIGN / 'summary.json', summarize())


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ('check-only', 'dry-run', 'launch', 'summarize'):
        actions.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    if args.check_only:
        from audit import audit
        print(json.dumps(audit(HERE / 'manifest.json', CAMPAIGN)))
    elif args.dry_run:
        from dry_run import dry_run
        print(json.dumps(dry_run(HERE / 'manifest.json', CAMPAIGN)))
    elif args.summarize:
        print(json.dumps(summarize()))
    else:
        launch()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - suppress provider-bearing exception messages
        print(json.dumps({'error': type(exc).__name__, 'detail': 'campaign check or dispatch failed; preserve started slots'}))
        raise SystemExit(2) from None
