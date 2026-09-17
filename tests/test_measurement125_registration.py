"""Preregistration and retained evidence stay independent of old real campaign slots."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "specs/125-snapshot-protocol-diagnostic/measurement"


@pytest.fixture
def modules(monkeypatch):
    loaded = {}
    for name in ("case", "observation", "supervision", "campaign", "analysis"):
        spec = importlib.util.spec_from_file_location("measurement125_registration_" + name, HERE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    return SimpleNamespace(**loaded)


@pytest.fixture
def registered(modules, monkeypatch, tmp_path):
    """Exercise registration against a real disposable product commit, not live src."""
    c = modules.campaign
    for name, content in {
        "src/offline_product.py": "VALUE = 1\n", "pyproject.toml": "[project]\nname = 'offline125'\n",
        "fixture/measurement.py": "MEASUREMENT = 1\n", "fixture/history.json": "{}\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(c, "REPO", tmp_path)
    c.git("add", "src", "pyproject.toml", "fixture")
    c.git("-c", "user.name=Offline125", "-c", "user.email=offline125@example.invalid",
          "commit", "-qm", "Synthetic registration product")
    monkeypatch.setattr(c, "PRODUCT_COMMIT", c.git("rev-parse", "HEAD"))
    monkeypatch.setattr(c, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(c, "measurement_paths", lambda: [tmp_path / "fixture/measurement.py"])
    monkeypatch.setattr(c, "historical_paths", lambda: [tmp_path / "fixture/history.json"])
    monkeypatch.setattr(c, "runtime_identity", lambda: {"fixture": "offline-runtime"})
    fixed = c.fixed_conditions()
    monkeypatch.setattr(c, "load_provider", lambda **kwargs: SimpleNamespace(safe_metadata=lambda model: fixed["provider"]))
    c.prepare()
    return c


def test_fixed_native_diagnostic_preserves_wire_roles_and_separate_denominator(modules):
    c = modules.campaign
    value = c.fixed_conditions()
    assert value["product_commit"] == "eefe389d14c2380ceb7db9089636f6a5ebe15e2a"
    assert value["limits"] == {"request_seconds": 600, "wall_seconds": 1320, "max_requests": 2,
                               "token_stop_threshold": 160000, "holdout_seconds": 5}
    assert value["planned_attempts"] == 1 and value["retries_or_replacements"] == 0
    assert value["runtime_options"]["message_roles"] == ["system", "user"]
    assert value["runtime_options"]["tools"] == 0
    assert value["holdouts"] == modules.case.holdouts()
    assert value["input_utf8"] == '{"limit":3}\n'
    assert value["contract"] == modules.case.contract().to_dict()
    prior = json.loads(c.REFERENCE.read_text())
    for field in ("contract", "contract_sha256", "input_utf8", "input_sha256", "input_profile",
                  "holdouts", "limits", "runtime_options", "sampling", "provider", "planned_attempts",
                  "schedule", "retries_or_replacements", "concurrency", "response_capture"):
        assert value[field] == prior[field]
    assert value["previous_campaign"] == {
        "campaign_id": prior["campaign_id"], "manifest_sha256": c.sha(c.REFERENCE),
        "product_commit": prior["product_commit"], "compiler_request": prior["compiler_request"],
    }
    assert value["condition_changes"] == {
        field: {"previous": prior[field], "current": value[field]}
        for field in ("campaign_id", "campaign_root", "product_commit", "compiler_request")
    }
    assert value["campaign_id"] == "diagnostic125-glm-5.2-snapshot-protocol-20260917"
    assert value["campaign_root"] != prior["campaign_root"]
    from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
    from famou.evaluator_bundle import _compiler_prompt
    prompt = _compiler_prompt(modules.case.contract(), value["input_profile"], invocation="snapshot")
    body = json.dumps({"model": "glm-5.2", "messages": [
        {"role": "system", "content": ISOLATED_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ], "stream": False}, ensure_ascii=False).encode()
    assert value["compiler_request"] == {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    assert value["compiler_request"] != prior["compiler_request"]
    assert "Runtime inputs[] has no path field" in prompt
    assert "source_label is not a file location" in prompt
    assert "do not prepend output/" in prompt
    assert c.REFERENCE.relative_to(c.REPO).as_posix() in c.pins(c.historical_paths())
    assert "specs/124-snapshot-request-protocol/spec.md" in c.pins(c.historical_paths())
    assert value["sampling"]["stream"] is False and value["sampling"]["max_tokens"] is None


def test_offline_registration_is_once_only_and_verifies_without_provider_requests(registered):
    manifest = registered.verify()
    assert manifest["planned_attempts"] == 1
    assert set(manifest["product_files"])
    assert set(manifest["product_files"]) == {"src/offline_product.py", "pyproject.toml"}
    assert set(manifest["measurement_files"]) == {"fixture/measurement.py"}
    assert set(manifest["historical_files"]) == {"fixture/history.json"}
    with pytest.raises(ValueError, match="already_exists"):
        registered.prepare()


def commit_registration(c):
    c.git("add", "manifest.json")
    c.git("-c", "user.name=Offline125", "-c", "user.email=offline125@example.invalid",
          "commit", "-qm", "Synthetic fixed registration")
    c.git("update-ref", "refs/remotes/origin/main", c.git("rev-parse", "HEAD"))


def test_committed_registration_verifies_only_the_disposable_repository(registered):
    with pytest.raises(subprocess.CalledProcessError):
        registered.verify(committed=True)
    commit_registration(registered)
    result = registered.verify(committed=True)
    assert result["product_commit"] == registered.PRODUCT_COMMIT
    assert result["product_commit"] != registered.git("rev-parse", "HEAD")


def test_product_drift_is_rejected_before_a_temporary_manifest_is_created(registered):
    registered.MANIFEST.unlink()
    (registered.REPO / "src/offline_product.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="product_changed"):
        registered.prepare()
    assert not registered.MANIFEST.exists()


@pytest.mark.parametrize("condition", ["limits", "input"])
def test_new_registration_cannot_change_the_prior_mathematical_conditions(modules, monkeypatch, condition):
    c = modules.campaign
    if condition == "limits":
        monkeypatch.setattr(c, "LIMITS", {**c.LIMITS, "max_requests": 3})
    else:
        monkeypatch.setattr(c, "INPUT_BYTES", b'{"limit":4}\n')
    with pytest.raises(ValueError, match="prior_conditions_changed"):
        c.fixed_conditions()


@pytest.mark.parametrize("condition", ["unpushed", "uncommitted_manifest", "uncommitted_pin"])
def test_unpushed_or_uncommitted_registration_is_rejected_before_launch(registered, condition):
    c = registered
    commit_registration(c)
    value = json.loads(c.MANIFEST.read_text())
    if condition == "unpushed":
        c.git("update-ref", "refs/remotes/origin/main", c.PRODUCT_COMMIT)
        expected = "registration_not_pushed"
    elif condition == "uncommitted_manifest":
        value["registered_utc"] = "different-registration-time"
        c.MANIFEST.write_text(json.dumps(value))
        expected = "manifest_not_committed"
    else:
        path = c.REPO / "fixture/measurement.py"
        path.write_text("MEASUREMENT = 2\n")
        value["measurement_files"]["fixture/measurement.py"] = c.sha(path)
        c.MANIFEST.write_text(json.dumps(value))
        expected = "registered_bytes_not_committed"
    with pytest.raises(ValueError, match=expected):
        c.verify(committed=True)


@pytest.mark.parametrize("field", [
    "limits", "contract", "contract_sha256", "input_utf8", "input_sha256", "input_profile",
    "holdouts", "planned_attempts", "retries_or_replacements", "sampling", "runtime_options",
    "compiler_request", "provider", "campaign_root", "primary", "secondary", "joint",
    "previous_campaign", "condition_changes",
])
def test_changed_fixed_conditions_are_rejected(registered, field):
    value = json.loads(registered.MANIFEST.read_text())
    value[field] = None
    registered.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="fixed_conditions"):
        registered.verify()


@pytest.mark.parametrize("group", ["product_files", "measurement_files", "historical_files"])
def test_registered_byte_drift_is_rejected(registered, group):
    value = json.loads(registered.MANIFEST.read_text())
    value[group][next(iter(value[group]))] = "0" * 64
    registered.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="registered_bytes"):
        registered.verify()


@pytest.mark.parametrize("group", ["product_files", "measurement_files", "historical_files"])
def test_file_set_omission_is_rejected(registered, group):
    value = json.loads(registered.MANIFEST.read_text())
    value[group].pop(next(iter(value[group])))
    registered.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="file_set"):
        registered.verify()


def journal(path, *, usage=None, pending=False):
    rows = [{"kind": "request_started", "index": 1, "requested_model": "glm-5.2",
             "request_sha256": "a" * 64, "request_timeout_seconds": 600}]
    if not pending:
        rows.append({"kind": "request_finished", "index": 1,
                     "outcome": "succeeded" if usage else "provider_error", "elapsed_seconds": 12.5,
                     "usage": usage, "known_usage": usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                     "failure_reason": None if usage else "transport_timeout", "response_status": None})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return rows


@pytest.mark.parametrize("state", ["missing", "pending", "timeout", "complete"])
def test_unknown_consumption_remains_unknown_and_known_usage_stays_subtotal(modules, tmp_path, state):
    path = tmp_path / "calls.jsonl"
    usage = {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
    if state != "missing":
        journal(path, usage=usage if state == "complete" else None, pending=state == "pending")
    value = modules.analysis.usage_summary(path)
    assert value["usage_complete"] is (state == "complete")
    assert value["total_usage"] == (usage if state == "complete" else None)
    assert value["cost_micros"] is None
    assert value["pending_requests"] == ([1] if state == "pending" else [])


@pytest.mark.parametrize("mutation", ["duplicate", "wrong_model", "bad_usage", "bad_subtotal", "third_request", "private_outcome"])
def test_malformed_usage_evidence_cannot_be_reported(modules, tmp_path, mutation):
    path = tmp_path / "calls.jsonl"
    rows = journal(path)
    if mutation == "duplicate":
        rows.append(rows[-1])
    elif mutation == "wrong_model":
        rows[0]["requested_model"] = "private-prose"
    elif mutation == "bad_usage":
        rows[-1]["usage"] = {"input_tokens": True, "output_tokens": 1, "total_tokens": 2}
    elif mutation == "bad_subtotal":
        rows[-1]["known_usage"]["total_tokens"] = 99
    elif mutation == "third_request":
        rows[0]["index"] = 3
    else:
        rows[-1]["outcome"] = "private-prose"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError):
        modules.analysis.usage_summary(path)


def test_transport_is_bound_to_recorded_request_and_projects_only_safe_values(modules, tmp_path):
    calls = tmp_path / "calls.jsonl"
    journal(calls)
    requests = modules.analysis.usage_summary(calls)["requests"]
    path = tmp_path / "transport.jsonl"
    row = {"request_index": 1, "stage": "evaluator_compiler", "outcome": "failure",
           "request_sha256": "a" * 64, "elapsed_ms": 600001, "request_body_bytes": 12000,
           "response_body_bytes": 0, "transport_observation": {
               "last_milestone": "wait_response_headers", "http_exchange_index": 1, "elapsed_ms": 33},
           "untrusted": "private-prose"}
    path.write_text(json.dumps(row) + "\n")
    assert "private-prose" not in json.dumps(modules.analysis.transport_summary(path, requests))
    row["request_sha256"] = "b" * 64
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="digest"):
        modules.analysis.transport_summary(path, requests)


def test_unstarted_holdout_is_not_counted_as_executed_and_match_is_recomputed(modules, tmp_path):
    c, a = modules.campaign, modules.analysis
    row = {"name": modules.case.holdouts()[0]["name"], "status": "failed", "matched": False,
           "snapshot_started": False, "observed": None, "error_class": "EvaluatorBundleError"}
    c.write_new(tmp_path / "holdouts/001.json", row)
    value = a.holdout_summary(tmp_path, {"fingerprint": "fixture"})
    assert value["recorded"] == 1 and value["executed"] == value["matched"] == 0
    row["matched"] = True
    (tmp_path / "holdouts/001.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="match_disagreement"):
        a.holdout_summary(tmp_path, {"fingerprint": "fixture"})


def failed_campaign(modules, monkeypatch, tmp_path):
    c, a = modules.campaign, modules.analysis
    manifest = c.fixed_conditions()
    for module in (c, a):
        monkeypatch.setattr(module, "REPO", tmp_path)
        monkeypatch.setattr(module, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(a, "HERE", tmp_path / "feature/measurement")
    a.HERE.parent.mkdir()
    monkeypatch.setattr(c, "git", lambda *args: "a" * 40)
    c.MANIFEST.write_text(json.dumps(manifest))

    def unavailable(*args):
        raise OSError("PRIVATE-PROVIDER-PROSE")

    c.run(manifest, runner=unavailable)
    return manifest, tmp_path / manifest["campaign_root"]


def test_supervisor_setup_exception_can_be_summarized_without_relaunch(modules, monkeypatch, tmp_path):
    manifest, _root = failed_campaign(modules, monkeypatch, tmp_path)
    value = modules.analysis.summarize(manifest)
    assert value["preparation_success"] == value["joint_success"] == 0
    assert value["holdouts"]["executed"] == 0
    assert value["usage"]["total_usage"] is None and not value["cleanup_verified"]
    assert value["process_status"] == "supervisor_failed"
    assert "PRIVATE-PROVIDER-PROSE" not in json.dumps(value)
    with pytest.raises(FileExistsError):
        modules.analysis.summarize(manifest)


@pytest.mark.parametrize("field", ["process_status", "exit_code", "registration_commit", "worker_status", "worker_stage"])
def test_public_report_rejects_arbitrary_process_or_worker_prose(modules, monkeypatch, tmp_path, field):
    manifest, root = failed_campaign(modules, monkeypatch, tmp_path)
    if field == "registration_commit":
        path = root / "started.json"
    elif field.startswith("worker_"):
        path = root / "attempt-001/worker-finished.json"
        path.write_text(json.dumps({"status": "failed", "stage": "setup", "frozen": None}))
    else:
        path = root / "attempt-001/finished.json"
    value = json.loads(path.read_text())
    value[field.removeprefix("worker_")] = "PRIVATE-PROVIDER-PROSE"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        modules.analysis.summarize(manifest)


def test_zero_exit_after_supervisor_deadline_cannot_be_joint_success(modules, monkeypatch, tmp_path):
    manifest, root = failed_campaign(modules, monkeypatch, tmp_path)
    path = root / "attempt-001/finished.json"
    value = json.loads(path.read_text())
    value.update(process_status="timed_out", exit_code=0, cleanup_verified=True)
    path.write_text(json.dumps(value))
    frozen = {"fingerprint": "a" * 64}
    (root / "attempt-001/worker-finished.json").write_text(json.dumps({
        "status": "completed", "stage": "finished", "frozen": frozen,
    }))
    usage = {"provider_requests": 2, "finished_requests": 2, "requests": [
        {"index": 1, "outcome": "succeeded", "request_sha256": manifest["compiler_request"]["sha256"]},
        {"index": 2, "outcome": "succeeded"},
    ]}
    monkeypatch.setattr(modules.analysis, "usage_summary", lambda path: usage)
    monkeypatch.setattr(modules.analysis, "frozen_snapshot", lambda *args: frozen)
    monkeypatch.setattr(modules.analysis, "holdout_summary", lambda *args: {"matched": 8})
    result = modules.analysis.summarize(manifest)
    assert result["preparation_success"] == 1 and result["joint_success"] == 0
