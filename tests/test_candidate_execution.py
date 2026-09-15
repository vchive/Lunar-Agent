import hashlib
import json

import pytest

from famou.candidate_bundle import CandidateSourceBundle
from famou.candidate_execution import (
    CandidateEvaluatorPin,
    CandidateExecutionAdmission,
    CandidateExecutionBudget,
    CandidateExecutionError,
    CandidateExecutionInput,
    admit_candidate_execution,
    build_candidate_execution_admission,
    parse_candidate_execution_admission,
)
from famou.candidate_workspace_plan import build_candidate_workspace_plan

CONTRACT = "a" * 64


def _plan():
    bundle = CandidateSourceBundle.from_dict({
        "schema_version": "1",
        "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT,
        "entrypoint": "main.py",
        "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    })
    return build_candidate_workspace_plan(bundle, contract_sha256=CONTRACT, command=["/bin/sh"])


def _admission(inputs=()):
    return build_candidate_execution_admission(
        _plan(),
        inputs=list(inputs),
        dependency_sha256="b" * 64,
        environment_sha256="c" * 64,
        evaluator={"kind": "exact-harness", "fingerprint": "d" * 64},
        budget={"timeout_seconds": 5, "max_output_bytes": 1024, "max_input_bytes": 1024, "max_processes": 1},
    )


def test_admission_digest_is_path_free_and_reorders_inputs():
    first = _admission([CandidateExecutionInput("z.txt", "fixture-z", 1, hashlib.sha256(b"z").hexdigest()), CandidateExecutionInput("a.txt", "fixture-a", 1, hashlib.sha256(b"a").hexdigest())])
    second = _admission(list(reversed(first.inputs)))
    assert first.digest() == second.digest()
    assert "workspace_path" not in json.dumps(first.to_dict())
    assert set(first.to_dict()) == {"schema_version", "protocol", "workspace_plan_sha256", "bundle_sha256", "contract_sha256", "inputs", "dependency_sha256", "environment_sha256", "evaluator", "output_contract_sha256", "budget", "admission_sha256"}


def test_admission_replays_self_digest_and_optional_byte_check(tmp_path):
    content = b"fixture"
    (tmp_path / "input.txt").write_bytes(content)
    admission = _admission([CandidateExecutionInput("input.txt", "fixture", len(content), hashlib.sha256(content).hexdigest())])
    parsed = CandidateExecutionAdmission.from_dict(admission.to_dict())
    verified = admit_candidate_execution(parsed, input_root=tmp_path)
    assert verified.admission_sha256 == admission.digest()
    assert verified.input_count == 1
    assert verified.total_input_bytes == len(content)
    assert parse_candidate_execution_admission(admission.to_dict()) == admission


def test_admit_accepts_workspace_plan_and_builds_verified_declaration(tmp_path):
    content = b"fixture"
    (tmp_path / "input.txt").write_bytes(content)
    verified = admit_candidate_execution(
        _plan(),
        input_root=tmp_path,
        inputs=[CandidateExecutionInput("input.txt", "fixture", len(content), hashlib.sha256(content).hexdigest())],
        dependency_sha256="b" * 64,
        environment_sha256="c" * 64,
        evaluator={"kind": "exact-harness", "fingerprint": "d" * 64},
        budget={"timeout_seconds": 5, "max_output_bytes": 1024, "max_input_bytes": 1024, "max_processes": 1},
    )
    assert verified.input_count == 1


@pytest.mark.parametrize("target", ["/tmp/x", "../x", "a//x", "a\\x", "a/./x"])
def test_input_target_is_logical_and_relative(target):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_"):
        CandidateExecutionInput(target, "fixture", 0, hashlib.sha256(b"").hexdigest())


def test_missing_changed_and_symlink_inputs_have_fixed_codes(tmp_path):
    item = CandidateExecutionInput("input.txt", "fixture", 1, hashlib.sha256(b"x").hexdigest())
    admission = _admission([item])
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_missing$"):
        admit_candidate_execution(admission, input_root=tmp_path)
    (tmp_path / "input.txt").write_bytes(b"y")
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_changed$"):
        admit_candidate_execution(admission, input_root=tmp_path)


def test_plan_pin_mismatch_happens_before_input_root(tmp_path):
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_plan_mismatch$"):
        build_candidate_execution_admission(
            _plan(), inputs=[], dependency_sha256="b" * 64, environment_sha256="c" * 64,
            evaluator=CandidateEvaluatorPin("exact", "d" * 64),
            budget=CandidateExecutionBudget(1, 1, 1, 1), expected_plan_sha256="e" * 64,
        )
