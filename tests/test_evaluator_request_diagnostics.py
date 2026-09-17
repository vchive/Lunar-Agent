"""Offline request diagnostics trust frozen evidence and never contact a provider."""
from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib import request as urllib_request

import pytest
from test_frozen_evaluator_bundle import _contract

from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
from famou.conversational import RuntimeContractCompiler
from famou.evaluator_bundle import _build_input_profile, _compiler_prompt
from famou.evolution import CandidateInputArtifact
from famou.runtime import OpenAICompatibleRuntime

SCRIPT = (Path(__file__).resolve().parents[1]
          / "specs/121-evaluator-prompt-protocol/diagnostics/analyze_requests.py")


@pytest.fixture
def diagnostic(monkeypatch):
    spec = importlib.util.spec_from_file_location("evaluator_request_diagnostics", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # reconstruct() prepends a frozen import path; do not retain it outside this test.
    monkeypatch.setattr(sys, "path", list(sys.path))
    return module


def _json(value):
    return json.dumps(value, sort_keys=True).encode()


@pytest.fixture
def evidence_fixture(diagnostic, tmp_path, monkeypatch):
    module = diagnostic
    monkeypatch.setattr(module, "REPO", tmp_path)
    campaign = tmp_path / ".lunar/fixture"
    slot = campaign / "slot-001-attempt-001"
    workspace = slot / "workspace"
    contract = _contract()
    contents = b"id\na\n"

    def write(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    write(workspace / "solve/contract.json", _json(contract.to_dict()))
    write(workspace / "data/raw/orders.csv", contents)
    profile = _build_input_profile(workspace, contract, (
        CandidateInputArtifact("data/raw/orders.csv", len(contents), module.sha(contents)),
    ))
    goal = "Assign every observed order and minimize route cost."
    prompts = (RuntimeContractCompiler._prompt(goal, None),
               _compiler_prompt(contract, profile, invocation="snapshot"))
    calls = []
    for index, prompt in enumerate(prompts, 1):
        calls.append({
            "kind": "request_started", "index": index,
            "request_sha256": module.sha(module.request_body(prompt, ISOLATED_SYSTEM_PROMPT, "fixture")),
            "request_timeout_seconds": 600,
        })
        calls.append({
            "kind": "request_finished", "index": index, "elapsed_seconds": 1 if index == 1 else 600,
            "outcome": "succeeded" if index == 1 else "provider_error",
            "failure_reason": None if index == 1 else "transport_timeout",
            "response_status": None,
            "observation": None if index == 1 else {
                "phase": "open_response", "elapsed_ms": 600000, "request_timeout_ms": 600000,
            },
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30} if index == 1 else None,
        })
    write(slot / "calls.jsonl", b"\n".join(_json(row) for row in calls) + b"\n")
    write(slot / "responses/response-001.json", _json({
        "text_utf8_bytes": 1, "text_sha256": "a" * 64,
        "redacted_prefix": "PRIVATE_RESPONSE_SENTINEL", "truncated": False,
        "redaction_applied": False,
    }))
    manifest = {
        "campaign_id": "fixture", "campaign_root": ".lunar/fixture", "product_commit": "fixture",
        "schedule": [{"case_key": "fixture", "attempt_id": slot.name}],
        "cases": {"fixture": {"goal": goal}}, "provider": {"requested_model": "fixture"},
        "product_files": {name: "b" * 64 for name in module.CRITICAL_SOURCE_FILES},
    }
    raw = _json(manifest)
    write(tmp_path / module.REGISTRATION, raw)
    monkeypatch.setattr(module, "REGISTRATION_SHA256", module.sha(raw))
    inventory = {
        "root": manifest["campaign_root"],
        "files": {path.relative_to(campaign).as_posix(): {
            "size": path.stat().st_size, "sha256": module.sha(path.read_bytes()),
        } for path in campaign.rglob("*") if path.is_file()},
    }
    raw = _json(inventory)
    write(tmp_path / module.EVIDENCE_MANIFEST, raw)
    monkeypatch.setattr(module, "EVIDENCE_MANIFEST_SHA256", module.sha(raw))
    return SimpleNamespace(module=module, campaign=campaign, slot=slot, inventory=inventory,
                           manifest=manifest, source=SCRIPT.parents[3] / "src")


def test_reconstruction_checks_all_evidence_without_provider_or_private_text(
    evidence_fixture, monkeypatch,
):
    fixture = evidence_fixture

    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline analysis attempted provider or network access")

    monkeypatch.setattr(OpenAICompatibleRuntime, "__init__", forbidden)
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", forbidden)
    monkeypatch.setattr(OpenAICompatibleRuntime, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib_request, "urlopen", forbidden)
    monkeypatch.setattr(Path, "home", forbidden)
    monkeypatch.setitem(sys.modules, "runtime_guard", SimpleNamespace(load_provider=forbidden))
    before = {path: path.read_bytes() for path in fixture.campaign.rglob("*") if path.is_file()}
    result = fixture.module.reconstruct(fixture.source)
    assert result["model_requests_made"] == 0
    assert result["evidence_manifest_sha256"] == fixture.module.EVIDENCE_MANIFEST_SHA256
    assert len(result["evidence_sha256"]) == len(fixture.inventory["files"]) == 4
    requests = result["tasks"][0]["requests"]
    assert len(requests) == 2 and all(row["recorded_hash_matches"] for row in requests)
    assert requests[1]["usage"] is None and requests[1]["response_status"] is None
    assert "PRIVATE_RESPONSE_SENTINEL" not in json.dumps(result)
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("relative", [
    "calls.jsonl", "workspace/solve/contract.json", "workspace/data/raw/orders.csv",
    "responses/response-001.json",
])
@pytest.mark.parametrize("mutation", ["same_size", "append", "truncate"])
def test_modified_raw_evidence_is_rejected_before_use(evidence_fixture, relative, mutation):
    fixture = evidence_fixture
    path = fixture.slot / relative
    original = path.read_bytes()
    changed = (bytes([original[0] ^ 1]) + original[1:] if mutation == "same_size"
               else original + b" " if mutation == "append" else original[:-1])
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="^evidence_file_mismatch$"):
        fixture.module.reconstruct(fixture.source)


def test_modified_evidence_inventory_cannot_repin_a_changed_journal(evidence_fixture):
    fixture = evidence_fixture
    path = fixture.slot / "calls.jsonl"
    raw = path.read_bytes().replace(b"600", b"601")
    path.write_bytes(raw)
    row = fixture.inventory["files"][path.relative_to(fixture.campaign).as_posix()]
    row.update(size=len(raw), sha256=fixture.module.sha(raw))
    inventory_path = fixture.module.REPO / fixture.module.EVIDENCE_MANIFEST
    inventory_path.write_bytes(_json(fixture.inventory))
    with pytest.raises(ValueError, match="^evidence_manifest_mismatch$"):
        fixture.module.reconstruct(fixture.source)


def test_unregistered_evidence_is_rejected_even_when_bytes_are_available(evidence_fixture):
    fixture = evidence_fixture
    observed = {}
    with pytest.raises(ValueError, match="^evidence_file_unregistered$"):
        fixture.module.read_evidence(fixture.slot / "calls.jsonl", fixture.campaign, {}, observed)
    assert observed == {}


def _git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, stderr=subprocess.PIPE,
    ).decode().strip()


def test_frozen_git_product_ignores_current_source_and_is_repeatable(diagnostic, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    source = repo / "src/famou/prompt.py"
    source.parent.mkdir(parents=True)
    frozen = b"PROMPT = 'registered protocol'\n"
    source.write_bytes(frozen)
    _git(repo, "init", "-q")
    _git(repo, "add", "src")
    _git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Freeze fixture")
    manifest = {"product_commit": _git(repo, "rev-parse", "HEAD"),
                "product_files": {"src/famou/prompt.py": diagnostic.sha(frozen)}}
    monkeypatch.setattr(diagnostic, "REPO", repo)
    source.write_bytes(b"raise AssertionError('current source must not be imported')\n")
    first, second = tmp_path / "first", tmp_path / "second"
    diagnostic.extract_product(manifest, first)
    source.write_bytes(b"PROMPT = 'another unregistered protocol'\n")
    diagnostic.extract_product(manifest, second)
    assert (first / "src/famou/prompt.py").read_bytes() == frozen
    assert (second / "src/famou/prompt.py").read_bytes() == frozen
    assert source.read_bytes() == b"PROMPT = 'another unregistered protocol'\n"
    manifest["product_files"]["src/famou/prompt.py"] = diagnostic.sha(source.read_bytes())
    with pytest.raises(ValueError, match="^product_bytes_mismatch$"):
        diagnostic.extract_product(manifest, tmp_path / "wrong-pin")


def test_real_evidence_inventory_pin_matches_committed_postrun(diagnostic):
    frozen = subprocess.check_output([
        "git", "show", f"{diagnostic.EVIDENCE_MANIFEST_COMMIT}:{diagnostic.EVIDENCE_MANIFEST}",
    ], cwd=diagnostic.REPO)
    assert diagnostic.sha(frozen) == diagnostic.EVIDENCE_MANIFEST_SHA256
    assert diagnostic.evidence_inventory(diagnostic.registration()) == json.loads(frozen)["files"]
