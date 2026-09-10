"""Materialize four fresh inputs and a credential-free registration without model calls."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from famou.effect_adapters import famou_case_content_digest
from famou.effect_trial import TrialBaseline, TrialSuite, _canonical_bytes, _profile_digest
from famou.profiles import ModelProfile
from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import WorkflowManifest

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAMPAIGN_ID = 'real-eval-glm-5.2-staged-20260910'
CAMPAIGN = REPO / '.lunar' / CAMPAIGN_ID
IMPLEMENTATION = '80f5af10f4a25dab5c5aa2ad767e3b78994f34a3'
OLD = REPO / '.lunar/real-eval-glm-5.2-high-score-20260909'
KIT = REPO / '.lunar/high-score-case-selection-20260909/kit-build'
SELECTION = KIT.parent / 'baseline-audit.json'
HARNESS_PYTHON = REPO / '.lunar/harness-venv-high-score-20260909/bin/python'
ORDER = [('M', 'sheet_metal_nesting'), ('S', 'china_post_pickup_optimization'),
         ('S', 'sheet_metal_nesting'), ('M', 'china_post_pickup_optimization')]
POLICY = StagePolicy(300, 2400, 120, 32)


def require(ok, message='measurement preparation failed'):
    if not ok:
        raise ValueError(message)


def sha(path):
    require(path.is_file() and not path.is_symlink(), 'expected a regular frozen file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_new(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(_canonical_bytes(payload))
        stream.flush()
        os.fsync(stream.fileno())


def expected_request(suite, profile_sha):
    case = suite.cases[0]
    return {
        'schema_version': '1', 'mode': 'normal', 'benchmark': suite.benchmark.to_dict(),
        'case': case.public_identity(), 'run_index': 1, 'requested_model': 'glm-5.2',
        'model_profile_sha256': profile_sha, 'entrypoint': case.entrypoint,
        'public_files': [file.to_dict() for file in case.public_files], 'receipt_path': 'receipt.json',
    }


def baseline_projection(suite, audit):
    """Normalize actual platform scored/extracted records; do not synthesize comparison scores."""
    case = suite.cases[0]
    observations = audit['by_case'][case.key]['runs']
    require(len(observations) == 3 and all(
        r['evaluation_status'] == 'scored' and r['extraction_status'] == 'extracted'
        and r['conclusion_eligibility'] == 'eligible' and r['validity_score'] == 1
        for r in observations
    ), 'historical selection is no longer three of three valid')
    result = {
        'schema_version': '1', 'source': 'company-platform', 'experiment_id': audit['experiment_id'],
        'authority': 'descriptive', 'conclusion_eligibility': 'ineligible',
        'provenance': {'source': 'company-platform', 'adapter': 'agentserver'},
        'benchmark': suite.benchmark.to_dict(), 'evaluation_profile': suite.evaluation_profile.to_dict(),
        'model': {'requested': 'glm-5.2', 'effective': 'glm-5.2', 'evidence': 'provider_observed'},
        'cases': [{**case.public_identity(), 'harness': case.harness.to_dict(), 'runs': [
            {'run_index': r['run_index'] + 1, 'ready': True, 'extraction_status': 'completed',
             'validity_score': r['validity_score'], 'overall_score': r['overall_score']}
            for r in observations
        ]}],
    }
    TrialBaseline.from_dict(result)
    return result


def local_provider_snapshot():
    loader = REPO / '.lunar/real-eval-20260908/ccswitch.py'
    spec = importlib.util.spec_from_file_location('measurement_ccswitch', loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    configured = module.load_environment()
    require(configured['ANTHROPIC_MODEL'] == 'glm-5.2')
    require(all(configured.get(k) for k in ('FAMOU_MODEL_ENDPOINT', 'FAMOU_API_KEY',
                'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')))
    return {name: hashlib.sha256(configured[name].encode()).hexdigest()
            for name in ('FAMOU_MODEL_ENDPOINT', 'ANTHROPIC_BASE_URL')}


def main():
    require(not CAMPAIGN.exists() and not (HERE / 'manifest.json').exists(), 'registration already exists')
    import famou
    require(Path(famou.__file__).resolve().parent == REPO / 'src/famou')
    source_files = {p.relative_to(REPO).as_posix(): sha(p)
                    for p in sorted((REPO / 'src/famou').rglob('*.py'))}
    for relative, digest in source_files.items():
        content = subprocess.check_output(['git', 'show', f'{IMPLEMENTATION}:{relative}'], cwd=REPO)
        require(hashlib.sha256(content).hexdigest() == digest, 'implementation source changed')
    source_sha = object_sha(source_files)
    old = read(OLD / 'manifest.json')
    require(sha(OLD / 'manifest.json') == (OLD / 'manifest.sha256').read_text().strip())
    profile = ModelProfile.from_dict(read(REPO / old['slots'][0]['attempt_relpath'] / 'model-profile.json'))
    require(profile.model == 'glm-5.2' and profile.max_steps == 200
            and profile.timeout_seconds == 5400 and profile.max_total_tokens == 8_000_000)
    require(_profile_digest(profile) == old['identity']['model_profile_sha256'])
    endpoints = local_provider_snapshot()
    require(endpoints == {
        'FAMOU_MODEL_ENDPOINT': old['identity']['subject_endpoint_sha256'],
        'ANTHROPIC_BASE_URL': old['identity']['extractor_endpoint_sha256'],
    }, 'authorized provider endpoint identity changed')
    probe = '''import json, platform
from importlib.metadata import distributions
import anyio, pandas, numpy
from claude_agent_sdk import query, ClaudeAgentOptions
print(json.dumps({"python_version":platform.python_version(),"packages":{
 d.metadata["Name"].lower().replace("_","-"):d.version for d in distributions()}}))
'''
    environment = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    readiness = json.loads(subprocess.check_output([str(HARNESS_PYTHON), '-c', probe], env=environment, text=True))
    require(readiness['packages'] == read(OLD / 'readiness.json')['packages'], 'harness dependencies changed')
    readiness.update(model_calls=0, provider_configuration_complete=True,
                     endpoint_identities_unchanged=True, harness_python_sha256=sha(HARNESS_PYTHON))
    audit = read(SELECTION)
    require(audit['model'] == 'glm-5.2' and audit['agent_family'] == 'AgentServer/OpenCode')
    inputs = CAMPAIGN / 'inputs'
    inputs.mkdir(parents=True)
    write_new(inputs / 'profile.json', profile.to_dict())
    write_new(CAMPAIGN / 'readiness.json', readiness)
    cases = {}
    for key in dict.fromkeys(key for _, key in ORDER):
        kit = KIT / key
        suite = TrialSuite.from_dict(read(kit / 'suite.json'))
        case = suite.cases[0]
        original = next(slot for slot in old['slots'] if slot['case_key'] == key)
        require(case.key == key and len(suite.cases) == 1)
        require(case.digest == original['case_digest'] == famou_case_content_digest(kit / 'private'))
        require(case.harness.to_dict() == original['harness'])
        for descriptor in case.public_files:
            require(sha(kit / 'public' / descriptor.path) == descriptor.sha256)
        require(sha(kit / 'private/tests/extractor_agent.py') == case.harness.extractor_sha256)
        require(sha(kit / 'private/tests/evaluator.py') == case.harness.evaluator_sha256)
        write_new(inputs / f'{key}-suite.json', suite.to_dict())
        write_new(inputs / f'{key}-baseline.json', baseline_projection(suite, audit))
        cases[key] = {'suite': suite.to_dict(),
                      'public_root_rel': (kit / 'public').relative_to(REPO).as_posix(),
                      'private_root_rel': (kit / 'private').relative_to(REPO).as_posix()}
    slots = []
    for index, (arm, key) in enumerate(ORDER, 1):
        suite = TrialSuite.from_dict(cases[key]['suite'])
        request = expected_request(suite, _profile_digest(profile))
        request_sha = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        workflow = None
        if arm == 'S':
            workflow = StagedWorkflowConfig(WorkflowManifest(
                run_id=f'{CAMPAIGN_ID}-slot-{index:03d}', attempt_id=f'slot-{index:03d}-attempt-001',
                source_sha256=source_sha, suite_key=suite.benchmark.name, case_key=key,
                request_sha256=request_sha, model_profile_sha256=_profile_digest(profile),
                ceilings={'max_wall_seconds': 5400, 'max_tool_steps': 200,
                          'max_total_tokens': 8_000_000, 'max_cost_micros': None},
            ), POLICY).to_dict()
            write_new(inputs / f'slot-{index:03d}-workflow.json', workflow)
        slots.append({'index': index, 'arm': arm, 'case_key': key,
                      'request_sha256': request_sha, 'workflow_config': workflow})
    historical = {p.relative_to(REPO).as_posix(): sha(p) for p in [
        OLD / name for name in ('manifest.json', 'summary.json', 'audit.json', 'readiness.json')
    ]}
    historical[SELECTION.relative_to(REPO).as_posix()] = sha(SELECTION)
    for path in sorted((REPO / '.lunar').glob('real-eval-glm-5.1*/manifest.json')):
        historical[path.relative_to(REPO).as_posix()] = sha(path)
    frozen_paths = [*sorted(inputs.glob('*.json')), CAMPAIGN / 'readiness.json',
                    *sorted(HERE.glob('*.py')), *sorted((REPO / 'tests').rglob('*.py')), REPO / '.lunar/real-eval-20260908/ccswitch.py',
                    REPO / '.venv/bin/lunar-agent', HARNESS_PYTHON]
    frozen = {p.relative_to(REPO).as_posix(): sha(p) for p in frozen_paths}
    manifest = {
        'schema_version': '1', 'campaign_id': CAMPAIGN_ID,
        'registered_utc': datetime.now(UTC).isoformat(),
        'implementation_commit': IMPLEMENTATION, 'source_files_sha256': source_files,
        'source_sha256': source_sha, 'profile': profile.to_dict(),
        'profile_sha256': _profile_digest(profile), 'policy': {
            'master_seconds': 300, 'build_seconds': 2400, 'reserve_seconds': 120,
            'checkpoint_after_rounds': 32,
        },
        'execution': {'waves': [[1, 2], [3, 4]], 'concurrency': 2,
                      'subject_outer_seconds': 5430, 'harness_outer_seconds': 3630,
                      'slot_outer_seconds': 9300},
        'planned_attempts': 4, 'cases': cases, 'slots': slots, 'endpoints': endpoints,
        'frozen_files_sha256': frozen, 'historical_files_sha256': historical,
        'selection_evidence': {'experiment_id': audit['experiment_id'],
                               'source': 'Platform WebAgent/AgentServer (OpenCode)',
                               'baseline_audit_sha256': sha(SELECTION)},
        'outcomes': {'primary': 'per-case exact-harness validity after accepted subject receipt',
                     'unscored_failure': None, 'pooled_quality_mean': False,
                     'fixed_denominator_per_arm': 2, 'retries_or_replacements': 0,
                     'historical_attempts_in_denominator': 0},
        'limitations': ['descriptive_one_attempt_per_case_arm', 'not_webagent_reproduction',
                       'planning_prompt_history_output_contract_changed_together',
                       'same_ceilings_not_equal_generation_time', 'provider_cache_and_resource_contention_uncontrolled',
                       'public_only_projection_is_not_os_sandbox'],
    }
    write_new(HERE / 'manifest.json', manifest)
    write_new(CAMPAIGN / 'manifest.json', manifest)
    for root in (HERE, CAMPAIGN):
        with (root / 'manifest.sha256').open('x') as stream:
            stream.write(sha(HERE / 'manifest.json') + '\n')
    print(json.dumps({'prepared': True, 'campaign_id': CAMPAIGN_ID,
                      'manifest_sha256': sha(HERE / 'manifest.json'), 'model_calls': 0}))


if __name__ == '__main__':
    main()
