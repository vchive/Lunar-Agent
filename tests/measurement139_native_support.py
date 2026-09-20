"""Fresh native Feature 139 fixtures; only provider responses are replaced.

The reusable evaluator/contract builders contain synthetic local source. No
historical manifest, candidate, response or result is replayed by this helper.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from measurement139_support import feature139
from test_measurement134_case import SOURCE, fixture_contract, suite

from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
from famou.http_transport import TransportObservation, TransportResponse
from famou.runtime import ModelRequestFailure, ModelTurn

worker = importlib.import_module(f"{feature139.__name__}.worker")
runner = importlib.import_module(f"{feature139.__name__}.runner")
registration = importlib.import_module(f"{feature139.__name__}.registration")
observation = importlib.import_module(f"{feature139.__name__}.observation")
analysis = importlib.import_module(f"{feature139.__name__}.analysis")

CANDIDATE = '''import json, os
from pathlib import Path
from helper import choose
limit = json.loads((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "limit.json").read_bytes())["limit"]
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": choose(limit)}))
'''


@dataclass
class NativeFixture:
    root: Path
    slot: Path
    manifest_path: Path
    manifest: dict
    provider: object
    requests: list
    provider_calls: list
    worker: object = worker
    analysis: object = analysis
    runner: object = runner

    def result(self):
        return json.loads((self.slot / "worker-finished.json").read_text(encoding="utf-8"))


def prepare_worker(monkeypatch, tmp_path: Path, *, outcome="success") -> NativeFixture:
    """Create one admitted temporary slot with native CLI and observed fake model calls."""
    tmp_path = tmp_path.resolve()
    provider = observation.ProviderConfiguration(
        "https://offline.invalid/v1", "offline-fixture-secret", "glm-5.2",
    )
    manifest = registration.fixed_contract()
    manifest["campaign_root"] = ".lunar/offline139"
    manifest["provider_safe_metadata"] = provider.safe_metadata("glm-5.2")
    manifest_path = tmp_path / "manifest.json"
    runner.write_new(manifest_path, manifest)
    for module in (worker, runner, analysis):
        monkeypatch.setattr(module, "REPO", tmp_path)
        monkeypatch.setattr(module, "MANIFEST", manifest_path)
    commit = "a" * 40
    repository = SimpleNamespace(verify=lambda **_kwargs: SimpleNamespace(
        manifest=manifest, registration_commit=commit,
        manifest_sha256=runner.sha(manifest_path),
    ))
    monkeypatch.setattr(worker, "default_repository", lambda: repository)
    monkeypatch.setenv("FAMOU_MAX_RETRIES", "1")
    monkeypatch.setenv("FAMOU_RUNTIME_TIMEOUT", "600")
    root = tmp_path / manifest["campaign_root"]
    slot = root / manifest["attempt_id"]
    slot.mkdir(parents=True, mode=0o700)
    identity = {
        key: manifest[key] for key in ("registration_id", "campaign_id", "attempt_id")
    }
    identity.update(registration_commit=commit, manifest_sha256=runner.sha(manifest_path))
    for path in (root, slot):
        runner.write_new(path / "admission.json", {
            "schema_version": "1", **identity, "admitted_utc": "2026-09-20T00:00:00+00:00",
        })
        runner.write_new(path / "started.json", {
            **identity, "started_utc": "2026-09-20T00:00:00+00:00",
            **({"index": 1} if path == slot else {}),
        })
    requests, provider_calls = [], []

    def get_provider(**kwargs):
        assert (slot / "worker-started.json").is_file()
        provider_calls.append(kwargs)
        return provider

    def forbidden(*_args, **_kwargs):
        pytest.fail("offline fixture attempted a real provider or network")

    def native(runtime, messages, tools=(), timeout=None):
        index = len(requests) + 1
        requests.append(messages)
        assert runtime.model == "glm-5.2" and runtime.api_key == provider.api_key
        expected_timeout = 900 if index in (2, 3) else 600
        assert expected_timeout - 1 < timeout <= expected_timeout
        prompt = messages[-1]["content"]
        if index <= 3:
            assert not tools
            assert [item["role"] for item in messages] == ["system", "user"]
            assert messages[0]["content"] == ISOLATED_SYSTEM_PROMPT
        if index == 1:
            assert "contract compiler" in prompt
            data = fixture_contract().to_dict()
            data["problem_id"] = "offline139"
            if outcome == "contract_scope":
                data["hard_constraints"][1]["source_check"]["minimum"] = 1
            text = "private-invalid-contract" if outcome == "contract_response" else json.dumps({
                "status": "compiled", "contract": data,
            })
        elif index == 2:
            assert "compiling one frozen local evaluator bundle" in prompt
            if outcome == "compiler_provider_failure":
                raise ModelRequestFailure("private-provider-failure", "transport_timeout")
            text = "private-invalid-evaluator" if outcome == "compiler_response" else json.dumps({
                **suite(2), "evaluator_source": SOURCE,
                "objective": "Maximize the exact independently read value.",
            })
        elif index == 3:
            assert "independent adversarial evaluator auditor" in prompt
            text = "private-invalid-auditor" if outcome == "auditor_response" else json.dumps(suite(4))
        else:
            assert tools and "LUNAR_CANDIDATE_INPUT_ROOT" in prompt
            names = [item["function"]["name"] for item in tools]
            assert not any("exec" in name or "memory" in name for name in names)
            assert "private-generated-text" not in json.dumps(messages)
            if outcome == "candidate_provider_failure":
                raise ModelRequestFailure("private-provider-failure", "transport_timeout")
            files = {
                "solve/main.py": CANDIDATE,
                "solve/helper.py": "def choose(limit):\n    return limit\n",
            }
            if outcome == "candidate_source":
                files = {"solve/main.py": "raise ValueError('private-candidate-failure')\n"}
            text = json.dumps({"entrypoint": "solve/main.py", "files": files, "metadata": {}})
        return ModelTurn(text, response_model="glm-5.2", usage={
            "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
        })

    def exchange(request, timeout):
        body = json.loads(request.data)
        assert request.get_header("Authorization") == "Bearer " + provider.api_key
        turn = native(
            SimpleNamespace(model=body["model"], api_key=provider.api_key),
            body["messages"], body.get("tools", ()), timeout,
        )
        return TransportResponse(200, json.dumps({
            "model": turn.response_model,
            "choices": [{"message": {"content": turn.text}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }).encode(), TransportObservation("response_headers_received", 1, 1))

    monkeypatch.setattr(worker, "load_provider", get_provider)
    monkeypatch.setattr(observation._shared, "load_provider", forbidden)
    monkeypatch.setattr("famou.runtime.exchange", exchange)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)
    return NativeFixture(root, slot, manifest_path, manifest, provider, requests, provider_calls)
