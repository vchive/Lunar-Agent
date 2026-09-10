"""Local evidence fixtures; no provider, solver, extractor or dispatcher execution."""
import hashlib
import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("postrun069_audit_tests", Path(__file__).with_name("audit.py"))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audit.canonical(value))


@pytest.fixture
def registered(tmp_path, monkeypatch):
    repo = tmp_path.resolve()
    here = repo / "specs/069-webagent-normal-workflow/measurement"
    campaign = repo / ".lunar/real-eval-glm-5.2-staged-20260910"
    here.mkdir(parents=True)
    campaign.mkdir(parents=True)
    source = repo / "src/famou/example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"VALUE = 1\n")
    frozen = {}
    for name in ("prepare.py", "worker.py", "campaign.py"):
        path = here / name
        path.write_text("# Frozen fixture; never imported.\n")
        frozen[path.relative_to(repo).as_posix()] = audit.sha(path)
    history = repo / "history.json"
    write(history, {"observation": "historical"})
    slots = [{"index": index, "arm": arm, "case_key": case}
             for index, (arm, case) in enumerate(audit.ORDER, 1)]
    manifest = {
        "implementation_commit": audit.IMPLEMENTATION, "planned_attempts": 4,
        "campaign_id": campaign.name, "execution": {"waves": [[1, 2], [3, 4]], "concurrency": 2},
        "slots": slots, "source_files_sha256": {"src/famou/example.py": audit.sha(source)},
        "frozen_files_sha256": frozen, "historical_files_sha256": {"history.json": audit.sha(history)},
    }
    for directory in (here, campaign):
        write(directory / "manifest.json", manifest)
    digest = audit.sha(here / "manifest.json")
    for directory in (here, campaign):
        (directory / "manifest.sha256").write_text(digest + "\n")
        for name in ("prelaunch-audit.json", "dry-run.json"):
            write(directory / name, {"passed": True, "model_calls": 0, "manifest_sha256": digest})
    commit = "b" * 40
    git_bytes = {name: (here / name).read_bytes() for name in ("manifest.json", "prelaunch-audit.json", "dry-run.json")}
    write(campaign / "started.json", {"manifest_sha256": digest, "campaign_id": campaign.name,
        "planned_attempts": 4, "concurrency": 2, "registration_commit": commit, "started_unix_seconds": 100.0})

    def git(_repo, *args):
        if args[:3] == ("show", "-s", "--format=%ct"):
            return b"99\n"
        if args[0] == "ls-tree":
            return b"src/famou/example.py\n"
        identity = args[1]
        if identity == f"{audit.IMPLEMENTATION}:src/famou/example.py":
            return b"VALUE = 1\n"
        assert identity.startswith(commit + ":")
        return git_bytes[identity.rsplit("/", 1)[-1]]

    monkeypatch.setattr(audit, "_git", git)
    summary = {"all_slots_terminated": False, "slots": [
        {**slot, "started": False, "process_terminated": False, "report_sha256": None,
         "subject_receipt_accepted": False, "harness_receipt_accepted": False,
         "validity_score": None, "overall_score": None, "quality_score": None}
        for slot in slots]}
    dispatcher = SimpleNamespace(REPO=repo, CAMPAIGN=campaign, summarize=lambda: deepcopy(summary))
    binding_calls = []
    worker = SimpleNamespace(verify_bindings=lambda *args, **kwargs: binding_calls.append((args, kwargs)))
    monkeypatch.setattr(audit, "_load_frozen_modules", lambda _directory: (dispatcher, worker))
    monkeypatch.setattr(audit, "verify_runtime_import", lambda _repo: None)
    return SimpleNamespace(repo=repo, here=here, campaign=campaign, manifest=manifest,
                           digest=digest, summary=summary, dispatcher=dispatcher, binding_calls=binding_calls)


def finish_outer_slots(fixture):
    endings = []
    for index, start in enumerate((101.0, 101.2, 103.0, 103.2), 1):
        write(fixture.campaign / f"slot-{index:03d}-started.json", {
            "index": index, "manifest_sha256": fixture.digest, "started_unix_seconds": start})
        end = {"index": index, "manifest_sha256": fixture.digest, "elapsed_seconds": 1.0,
               "exit_code": None, "failure": "slot_timeout_or_launch_failure"}
        write(fixture.campaign / f"slot-{index:03d}-terminated.json", end)
        endings.append(end)
        fixture.summary["slots"][index - 1].update(started=True, process_terminated=True)
    fixture.summary["all_slots_terminated"] = True
    write(fixture.campaign / "terminated.json", {"manifest_sha256": fixture.digest,
          "terminated_unix_seconds": 105.0, "slots": endings})
    write(fixture.campaign / "summary.json", fixture.summary)


def test_partial_is_consistent_but_cannot_be_final(registered):
    before = {p: p.read_bytes() for p in registered.repo.rglob("*") if p.is_file()}
    result = audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign)
    assert result["passed"] is True and result["complete"] is False
    assert result["analysis_script_sha256"] == audit.sha(Path(audit.__file__))
    assert result["final_acceptance"] is False and result["files_written"] == result["model_calls"] == 0
    assert all(row["overall_score"] is None for row in result["summary"]["slots"])
    assert [args[4]["index"] for args, kwargs in registered.binding_calls] == [1, 2, 3, 4]
    assert all(kwargs == {"require_started": False} for args, kwargs in registered.binding_calls)
    with pytest.raises(audit.AuditError, match="incomplete"):
        audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign, require_complete=True)
    assert {p: p.read_bytes() for p in registered.repo.rglob("*") if p.is_file()} == before


def test_terminal_launch_failures_remain_unscored_in_final(registered):
    finish_outer_slots(registered)
    result = audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign, require_complete=True)
    assert result["complete"] is True and result["final_acceptance"] is True
    assert all(row["overall_score"] is None for row in result["summary"]["slots"])


@pytest.mark.parametrize("missing", ["summary.json", "terminated.json", "slot-004-terminated.json"])
def test_final_refuses_incomplete_material(registered, missing):
    finish_outer_slots(registered)
    (registered.campaign / missing).unlink()
    with pytest.raises(audit.AuditError):
        audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign, require_complete=True)


@pytest.mark.parametrize("target", ["history", "source", "registered_report", "final_summary"])
def test_actual_digest_and_final_projection_tampering_rejected(registered, target):
    if target == "history":
        write(registered.repo / "history.json", {"changed": True})
    elif target == "source":
        (registered.repo / "src/famou/example.py").write_text("VALUE = 2\n")
    elif target == "registered_report":
        write(registered.here / "prelaunch-audit.json", {"passed": True, "changed": True})
    else:
        finish_outer_slots(registered)
        changed = deepcopy(registered.summary)
        changed["slots"][0]["overall_score"] = 1
        write(registered.campaign / "summary.json", changed)
    with pytest.raises(audit.AuditError):
        audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign)


@pytest.mark.parametrize("extra", ["slot", "attempt"])
def test_extra_slot_or_attempt_rejected(registered, extra):
    if extra == "slot":
        (registered.campaign / "slots/005").mkdir(parents=True)
    else:
        path = registered.campaign / "slots/001/trial/cases/sheet_metal_nesting/runs/001/attempts"
        (path / "001").mkdir(parents=True)
        (path / "002").mkdir()
    with pytest.raises(audit.AuditError, match="extra"):
        audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign)


def test_wave_barrier_uses_estimate_with_explicit_tolerance():
    starts = {1: {}, 2: {}, 3: {"started_unix_seconds": 199.5}, 4: None}
    ends = {1: 199.0, 2: 200.0, 3: None, 4: None}
    audit.verify_waves(starts, ends)
    starts[3]["started_unix_seconds"] = 197.0
    with pytest.raises(audit.AuditError, match="order"):
        audit.verify_waves(starts, ends)
    ends[2] = None
    with pytest.raises(audit.AuditError, match="before wave one"):
        audit.verify_waves(starts, ends)


def test_active_summary_change_requires_new_read_only_observation(registered):
    calls = 0

    def moving_summary():
        nonlocal calls
        calls += 1
        value = deepcopy(registered.summary)
        if calls == 2:
            value["slots"][0]["started"] = True
        return value

    registered.dispatcher.summarize = moving_summary
    with pytest.raises(audit.AuditError, match="advanced during observation"):
        audit.audit_registered_campaign(registered.here / "manifest.json", registered.campaign)


def test_public_projection_uses_file_bytes_not_claims(tmp_path):
    public = tmp_path / "case/data.json"
    public.parent.mkdir()
    public.write_bytes(b"{}")
    suite = {"cases": [{"public_files": [{"path": "data.json", "size": 2,
              "sha256": hashlib.sha256(b"{}").hexdigest()}]}]}
    evidence = audit.Evidence(tmp_path)
    audit.verify_public(tmp_path, suite, evidence)
    public.write_bytes(b"[]")
    with pytest.raises(audit.AuditError):
        audit.verify_public(tmp_path, suite, evidence)


def test_import_from_another_repository_is_rejected(tmp_path):
    with pytest.raises(audit.AuditError, match="imported runtime"):
        audit.verify_runtime_import(tmp_path)
