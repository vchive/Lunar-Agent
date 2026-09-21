"""Typed source checks keep requirements and split generated probes by evidence capability."""
import hashlib
import json
from dataclasses import replace

import pytest
from test_frozen_evaluator_bundle import EVALUATOR_SOURCE, BundleRuntime, _contract, _envelope
from test_snapshot_evaluator_bundle import SNAPSHOT_SOURCE

from lunar_evolution.algorithm import AlgorithmProblemContract, ConstraintSpec, SourceCheckSpec
from lunar_evolution.conversational import (
    ContractCompilationError,
    RuntimeContractCompiler,
    _parse_response,
)
from lunar_evolution.evaluator_bundle import (
    EvaluatorBundleError,
    UnsupportedEvaluatorConstraintsError,
    _parse_envelope,
    compile_evaluator_bundle,
    load_evaluator_bundle,
    validate_evaluator_capabilities,
)
from lunar_evolution.evolution import CandidateInputArtifact
from lunar_evolution.source_constraints import source_constraints


def source_contract(minimum=2):
    original = _contract()
    source = ConstraintSpec('two-files', 'Deliver at least two Python files.', 'user_confirmed',
                            'independent', verification_scope='source',
                            source_check=SourceCheckSpec('python_file_count', minimum))
    return replace(original, hard_constraints=(*original.hard_constraints, source))


def compile_source(runtime, root, contract):
    target = root / 'data/raw/orders.csv'
    target.parent.mkdir(parents=True, exist_ok=True)
    content = b'id\nobserved-order\n'
    target.write_bytes(content)
    descriptor = CandidateInputArtifact('data/raw/orders.csv', len(content), hashlib.sha256(content).hexdigest())
    return compile_evaluator_bundle(runtime, contract, root, inputs=(descriptor,), invocation='snapshot', timeout=2)


@pytest.mark.parametrize('minimum', [1, 2, 64])
def test_typed_source_check_roundtrips_and_is_bound_to_contract(minimum):
    contract = source_contract(minimum)
    payload = contract.to_dict()
    assert payload['hard_constraints'][-1]['source_check'] == {'kind': 'python_file_count', 'minimum': minimum}
    assert AlgorithmProblemContract.from_dict(payload) == contract
    compiled = _parse_response(json.dumps({'status': 'compiled', 'contract': payload}))
    assert compiled.contract == contract
    assert contract.digest() != _contract().digest()
    assert source_constraints(contract) == (contract.hard_constraints[-1],)
    assert 'source_check' not in _contract().canonical_json()
    assert _contract().digest() == '4770a00b1c5433283381fa8c6bfcf60df511551892492f9082b63584455509a3'


@pytest.mark.parametrize('check', [None, {}, [], True, 'python_file_count',
    {'kind': 'python_file_count'}, {'minimum': 2}, {'kind': 'imports', 'minimum': 2},
    {'kind': 'python_file_count', 'minimum': 2, 'maximum': 3},
    *[{'kind': 'python_file_count', 'minimum': n} for n in [0, 65, -1, True, '2', 2.0, None]],
])
def test_invalid_source_check_is_not_silently_ignored(check):
    payload = source_contract().to_dict()
    payload['hard_constraints'][-1]['source_check'] = check
    with pytest.raises((ValueError, TypeError), match='source_check'):
        AlgorithmProblemContract.from_dict(payload)
    with pytest.raises(ContractCompilationError, match='source_check'):
        _parse_response(json.dumps({'status': 'compiled', 'contract': payload}))


@pytest.mark.parametrize('scope', [None, 'output', 'execution'])
def test_source_check_requires_explicit_source_scope(scope):
    payload = source_contract().to_dict()
    source = payload['hard_constraints'][-1]
    if scope is None:
        del source['verification_scope']
    else:
        source['verification_scope'] = scope
    with pytest.raises(ValueError, match='requires source'):
        AlgorithmProblemContract.from_dict(payload)


def test_prompt_states_count_limit_and_never_substitutes_for_behavior():
    prompt = RuntimeContractCompiler._prompt('Deliver two files.', None)
    for marker in ('python_file_count', 'minimum', 'including empty files', 'lowercase .py',
                   'does not prove syntax validity', 'Never replace those requirements'):
        assert marker in prompt


def test_snapshot_partitions_output_coverage_and_frozen_resume_preserves_full_contract(tmp_path):
    contract = source_contract()
    runtime = BundleRuntime(_envelope(SNAPSHOT_SOURCE))
    bundle = compile_source(runtime, tmp_path, contract)
    assert runtime.bundle_calls == runtime.audit_calls == 1
    for name in ('probes.json', 'audit.json'):
        assert json.loads((bundle.root / name).read_bytes())['constraint_coverage'] == ['serve-all']
    for prompt in (*runtime.bundle_prompts, *runtime.audit_prompts):
        assert '"source_check"' in prompt and '"two-files"' in prompt
        assert 'exactly these output constraint IDs: ["serve-all"]' in prompt
        assert 'independently checked source IDs' in prompt
    assert json.loads((bundle.root / 'manifest.json').read_bytes())['contract_sha256'] == contract.digest()
    before = {p.name: p.read_bytes() for p in bundle.root.iterdir()}
    assert compile_source(runtime, tmp_path, contract) == bundle
    assert load_evaluator_bundle(bundle.root, contract, invocation='snapshot', timeout=2) == bundle
    assert runtime.bundle_calls == runtime.audit_calls == 1
    assert before == {p.name: p.read_bytes() for p in bundle.root.iterdir()}
    with pytest.raises(EvaluatorBundleError, match='contract digest'):
        load_evaluator_bundle(bundle.root, source_contract(3), invocation='snapshot')


@pytest.mark.parametrize('bad_coverage', [[], ['two-files'], ['serve-all', 'two-files']])
def test_compiler_cannot_claim_source_or_drop_output_coverage(bad_coverage):
    envelope = _envelope(SNAPSHOT_SOURCE)
    envelope['constraint_coverage'] = bad_coverage
    with pytest.raises(EvaluatorBundleError, match='coverage must exactly match'):
        _parse_envelope(json.dumps(envelope), source_contract(), invocation='snapshot')


@pytest.mark.parametrize('unsupported', ['legacy_mode', 'missing_check', 'soft', 'execution'])
def test_incomplete_capability_still_stops_before_model_and_workspace(tmp_path, unsupported):
    contract = source_contract()
    invocation = 'snapshot'
    if unsupported == 'legacy_mode':
        invocation = 'candidate'
    elif unsupported == 'missing_check':
        contract = replace(contract, hard_constraints=(replace(contract.hard_constraints[-1], source_check=None),))
    elif unsupported == 'soft':
        contract = replace(contract, hard_constraints=contract.hard_constraints[:-1], soft_constraints=(contract.hard_constraints[-1],))
    else:
        contract = replace(contract, hard_constraints=(replace(contract.hard_constraints[-1], verification_scope='execution', source_check=None),))
    root = tmp_path / 'absent'
    runtime = BundleRuntime(_envelope(EVALUATOR_SOURCE))
    with pytest.raises(UnsupportedEvaluatorConstraintsError):
        compile_evaluator_bundle(runtime, contract, root, invocation=invocation)
    assert not root.exists() and runtime.bundle_calls == runtime.audit_calls == 0
    with pytest.raises(UnsupportedEvaluatorConstraintsError):
        validate_evaluator_capabilities(contract, invocation=invocation)


def test_many_failed_source_requirements_keep_all_evidence_and_bounded_report():
    from lunar_evolution.algorithm import MAX_ERROR_INFO
    from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
    from lunar_evolution.source_constraints import source_check_evidence, source_failure_report

    base = source_contract()
    requirements = tuple(replace(base.hard_constraints[-1], id=f'count-{i}') for i in range(64))
    contract = replace(base, hard_constraints=requirements)
    bundle = CandidateSourceBundle(contract.digest(), 'main.py', (CandidateSourceFile('main.py', 0, hashlib.sha256(b'').hexdigest()),))
    evidence = source_check_evidence(contract, bundle)
    assert len(evidence['checks']) == 64 and evidence['validity'] is False
    report = source_failure_report('exact', evidence)
    assert report.validity == 0 and report.combined_score == 0
    assert len(report.error_info) == MAX_ERROR_INFO
    assert report.quality is None


def test_pure_evidence_cannot_omit_unsupported_mixed_requirements():
    from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
    from lunar_evolution.source_constraints import source_check_evidence

    base = source_contract()
    unsupported = replace(base.hard_constraints[-1], id='behavior', source_check=None, verification_scope='execution')
    contract = replace(base, soft_constraints=(unsupported,))
    bundle = CandidateSourceBundle(contract.digest(), 'main.py', (CandidateSourceFile('main.py', 0, hashlib.sha256(b'').hexdigest()),))
    with pytest.raises(ValueError, match='unsupported'):
        source_check_evidence(contract, bundle)


def test_large_supported_evidence_has_its_own_bound_above_bundle_size():
    from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
    from lunar_evolution.candidate_evaluation_spec import canonical_json
    from lunar_evolution.source_constraints import (
        MAX_SOURCE_CHECK_BYTES,
        parse_source_check_evidence,
        source_check_evidence,
    )

    base = source_contract()
    requirements = tuple(replace(base.hard_constraints[-1], id='count-' + 'x' * 440 + str(i)) for i in range(64))
    contract = replace(base, hard_constraints=requirements)
    paths = ['/'.join(['"' * 200] * 4) + '/' + str(i) + '.py' for i in range(64)]
    bundle = CandidateSourceBundle(contract.digest(), paths[0], tuple(CandidateSourceFile(p, 0, hashlib.sha256(b'').hexdigest()) for p in paths))
    evidence = source_check_evidence(contract, bundle)
    raw = canonical_json(evidence, maximum=MAX_SOURCE_CHECK_BYTES)
    assert 128 * 1024 < len(raw) <= MAX_SOURCE_CHECK_BYTES
    assert parse_source_check_evidence(raw, contract, bundle_sha256=bundle.digest()) == evidence
