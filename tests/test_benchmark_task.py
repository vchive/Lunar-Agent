from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_cli import _write_evolution_contract

from famou import cli
from famou.algorithm import AlgorithmProblemContract
from famou.benchmark_task import (
    BenchmarkTaskEnvelope,
    BenchmarkTaskError,
    admit_benchmark_task_envelope,
    parse_benchmark_task_envelope,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
P_SHA = "d" * 64


def _payload() -> dict:
    return {
        "schema_version": "1",
        "protocol": "lunar-benchmark-task-v1",
        "benchmark": {"name": "skydiscover", "release_version": "fixture-1", "publication_digest": f"sha256:{SHA_A}"},
        "task": {"key": "routing-1", "revision_id": "rev-1", "digest": f"sha256:{SHA_B}", "entrypoint": "task.json"},
        "contract_sha256": SHA_C,
        "inputs": [{"path": "task.json", "size": 13, "sha256": hashlib.sha256(b'{"items":[1]}').hexdigest()}],
        "model": {"requested": "fixture-model", "profile_sha256": P_SHA},
        "evaluator": {"kind": "exact_harness", "extractor_sha256": SHA_A, "evaluator_sha256": SHA_B},
        "candidate": {"kind": "single_file", "filename": "candidate.py"},
        "budget": {"attempts": 2, "timeout_seconds": 30.0, "max_total_tokens": 1000, "max_cost_micros": 5000},
    }


def test_roundtrip_and_digests_are_stable():
    envelope = BenchmarkTaskEnvelope.from_dict(_payload())
    assert envelope.to_dict() == _payload()
    assert len(envelope.digest()) == 64
    assert len(envelope.comparison_digest()) == 64
    assert envelope.digest() == BenchmarkTaskEnvelope.from_dict(json.loads(json.dumps(_payload()))).digest()


def test_sky_and_llm4ad_mapping_share_comparison_identity():
    first = _payload()
    second = _payload()
    first["benchmark"] = {"name": "skydiscover", "release_version": "v1", "publication_digest": f"sha256:{SHA_A}"}
    second["benchmark"] = {"name": "llm4ad", "release_version": "v9", "publication_digest": f"sha256:{SHA_A}"}
    assert BenchmarkTaskEnvelope.from_dict(first).comparison_digest() == BenchmarkTaskEnvelope.from_dict(second).comparison_digest()


@pytest.mark.parametrize("mutation", [
    lambda p: p.update({"unknown": 1}),
    lambda p: p["inputs"][0].update({"path": "../secret"}),
    lambda p: p["candidate"].update({"filename": "/tmp/candidate.py"}),
    lambda p: p["model"].update({"requested": "token=secret"}),
    lambda p: p["budget"].update({"attempts": 0}),
])
def test_invalid_envelope_is_rejected(mutation):
    payload = _payload()
    mutation(payload)
    with pytest.raises(BenchmarkTaskError):
        BenchmarkTaskEnvelope.from_dict(payload)


def test_admission_rechecks_contract_and_input_bytes(tmp_path: Path):
    source = tmp_path / "task.json"
    content = b'{"items":[1]}'
    source.write_bytes(content)
    envelope = BenchmarkTaskEnvelope.from_dict(_payload())
    admitted = admit_benchmark_task_envelope(
        envelope, contract_sha256=SHA_C, input_root=tmp_path,
        model_profile_sha256=P_SHA,
        evaluator_fingerprint=SHA_B,
    )
    assert admitted.envelope_sha256 == envelope.digest()
    source.write_bytes(b'{"items":[2]}')
    with pytest.raises(BenchmarkTaskError, match="input"):
        admit_benchmark_task_envelope(
            envelope, contract_sha256=SHA_C, input_root=tmp_path,
            model_profile_sha256=P_SHA, evaluator_fingerprint=SHA_B,
        )


def test_admission_requires_caller_model_and_evaluator_pins(tmp_path: Path):
    content = b'{"items":[1]}'
    (tmp_path / "task.json").write_bytes(content)
    envelope = BenchmarkTaskEnvelope.from_dict(_payload())
    with pytest.raises(BenchmarkTaskError, match="model_mismatch"):
        admit_benchmark_task_envelope(
            envelope, contract_sha256=SHA_C, input_root=tmp_path,
            evaluator_fingerprint=SHA_B,
        )
    with pytest.raises(BenchmarkTaskError, match="evaluator_mismatch"):
        admit_benchmark_task_envelope(
            envelope, contract_sha256=SHA_C, input_root=tmp_path,
            model_profile_sha256=P_SHA,
        )


def test_parser_rejects_duplicate_json_keys(tmp_path: Path):
    path = tmp_path / "task.json"
    path.write_text('{"schema_version":"1","schema_version":"1"}')
    with pytest.raises(BenchmarkTaskError):
        parse_benchmark_task_envelope(path)


def test_cli_validate_dispatches_without_home_initialization(tmp_path: Path, monkeypatch, capsys):
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path)
    contract = AlgorithmProblemContract.from_dict(json.loads(contract_path.read_text()))
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    content = b'{"items":[1]}'
    (input_root / "task.json").write_bytes(content)
    payload = _payload()
    payload["contract_sha256"] = contract.digest()
    payload["inputs"][0]["size"] = len(content)
    task_path = tmp_path / "task-envelope.json"
    task_path.write_text(json.dumps(payload))

    monkeypatch.setattr(cli, "_config", lambda *_args, **_kwargs: pytest.fail("initialized home"))
    assert cli.main([
        "benchmark-task", "validate", str(task_path), "--contract", str(contract_path),
        "--input-root", str(input_root), "--model-profile-sha256", P_SHA,
        "--evaluator-fingerprint", SHA_B, "--json",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "validated"
    assert output["input_count"] == 1
    assert not (tmp_path / ".famou").exists()
