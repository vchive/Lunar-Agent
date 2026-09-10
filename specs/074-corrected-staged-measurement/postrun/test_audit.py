"""Offline two-slot acceptance boundaries; never dispatch providers or historical candidates."""
import hashlib
import importlib.util
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(
        "test_postrun074_" + name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("audit")
report = load("render_report")


@pytest.fixture
def top_level(tmp_path, monkeypatch):
    actual_adapter, legacy = audit.dependencies()
    campaign, measurement = tmp_path / "campaign", tmp_path / "measurement"
    campaign.mkdir()
    measurement.mkdir()
    slots = [{"index": index, "arm": "S", "budget_arm": arm, "case_key": case}
             for index, (arm, case) in enumerate(actual_adapter.ORDER, 1)]
    manifest, digest = {"slots": slots}, "d" * 64
    summary = {
        "manifest_sha256": digest, "planned_attempts": 2, "all_slots_terminated": False,
        "slots": [{**slot, "started": False, "process_terminated": False,
                   "report_sha256": None, "subject_receipt_accepted": False,
                   "harness_receipt_accepted": False} for slot in slots],
    }
    calls = []
    dispatcher = SimpleNamespace(REPO=tmp_path, CAMPAIGN=campaign,
                                 summarize=lambda: deepcopy(summary))
    worker = SimpleNamespace(
        verify_bindings=lambda *args, **kwargs: calls.append((args[4]["index"], kwargs))
    )
    adapter = SimpleNamespace(
        REPO=tmp_path, CAMPAIGN=campaign, IMPLEMENTATION=actual_adapter.IMPLEMENTATION,
        load_campaign=lambda: dispatcher, load_worker=lambda: worker,
        load_prior_postrun=actual_adapter.load_prior_postrun,
    )
    monkeypatch.setattr(audit, "MEASUREMENT", measurement)
    monkeypatch.setattr(audit, "dependencies", lambda: (adapter, legacy))
    monkeypatch.setattr(audit, "verify_registration", lambda *args: (
        manifest, digest, {"registration_commit": "c" * 40, "started_unix_seconds": 100.0}
    ))
    monkeypatch.setattr(legacy, "verify_runtime_import", lambda repo: None)
    return SimpleNamespace(
        repo=tmp_path, campaign=campaign, measurement=measurement, manifest=manifest,
        summary=summary, calls=calls, legacy=legacy, digest=digest, dispatcher=dispatcher,
    )


def inspect(t, *, final=False):
    return audit.audit_registered_campaign(t.measurement / "manifest.json", t.campaign,
                                          require_complete=final)


def finish(t):
    endings = []
    for index, start in enumerate((101.0, 101.1), 1):
        began = {"index": index, "manifest_sha256": t.digest, "started_unix_seconds": start}
        ended = {"index": index, "manifest_sha256": t.digest, "elapsed_seconds": 1.0,
                 "exit_code": None, "failure": "slot_timeout_or_launch_failure"}
        (t.campaign / f"slot-{index:03d}-started.json").write_bytes(t.legacy.canonical(began))
        (t.campaign / f"slot-{index:03d}-terminated.json").write_bytes(t.legacy.canonical(ended))
        t.summary["slots"][index - 1].update(started=True, process_terminated=True)
        endings.append(ended)
    t.summary["all_slots_terminated"] = True
    (t.campaign / "terminated.json").write_bytes(t.legacy.canonical({
        "manifest_sha256": t.digest, "terminated_unix_seconds": 104.0, "slots": endings,
    }))
    (t.campaign / "summary.json").write_bytes(t.legacy.canonical(t.summary))


def test_partial_audit_checks_exactly_two_slots_without_dispatch(top_level):
    t = top_level
    result = inspect(t)
    assert result["passed"] is True
    assert result["complete"] is result["final_acceptance"] is False
    assert t.calls == [(i, {"require_started": False}) for i in (1, 2)]
    assert result["files_written"] == result["model_calls"] == 0
    assert result["credentials_loaded"] is False
    assert [stage["index"] for stage in result["stages"]] == [1, 2]
    assert all(stage["master_duration_seconds"] is None for stage in result["stages"])
    with pytest.raises(ValueError, match="incomplete"):
        inspect(t, final=True)


def test_accepted_subject_flag_reaches_real_pinned_stage_validator(top_level, monkeypatch):
    t = top_level
    t.summary["slots"][1]["subject_receipt_accepted"] = True
    monkeypatch.setattr(t.legacy, "verify_slot",
                        lambda *args: ({"index": args[0]["index"]}, None, None))
    with pytest.raises(ValueError, match="accepted staged subject lacks workflow"):
        inspect(t)


def test_stage_validator_loader_refuses_changed_pinned_sha(monkeypatch):
    adapter, _legacy = audit.dependencies()
    expected = "6e060bbbb60754bd38696bed75f57dd9a0ca95f2d3a2487875c72d709739c307"
    assert adapter.PRIOR_FILES["postrun/audit.py"] == expected
    assert callable(adapter.load_prior_postrun().stage_evidence)
    monkeypatch.setitem(adapter.PRIOR_FILES, "postrun/audit.py", "0" * 64)
    with pytest.raises(ValueError, match="pinned measurement helper changed"):
        adapter.load_prior_postrun()


def test_final_audit_requires_both_matching_outer_endings_and_is_read_only(top_level):
    t = top_level
    finish(t)
    before = {p: p.read_bytes() for p in t.campaign.rglob("*") if p.is_file()}
    result = inspect(t, final=True)
    assert result["complete"] is result["final_acceptance"] is True
    assert len(result["slots"]) == len(result["stages"]) == 2
    assert {p: p.read_bytes() for p in t.campaign.rglob("*") if p.is_file()} == before
    (t.campaign / "slot-002-terminated.json").unlink()
    with pytest.raises(ValueError):
        inspect(t, final=True)


@pytest.mark.parametrize("change", ["saved_summary", "manifest_digest", "slot_endings", "time"])
def test_final_audit_refuses_contradictory_campaign_completion(top_level, change):
    t = top_level
    finish(t)
    if change == "saved_summary":
        saved = deepcopy(t.summary)
        saved["planned_attempts"] = 4
        (t.campaign / "summary.json").write_bytes(t.legacy.canonical(saved))
    else:
        path = t.campaign / "terminated.json"
        ended = t.legacy.read(path)
        if change == "manifest_digest":
            ended["manifest_sha256"] = "0" * 64
        elif change == "slot_endings":
            ended["slots"].pop()
        else:
            ended["terminated_unix_seconds"] = 90.0
        path.write_bytes(t.legacy.canonical(ended))
    with pytest.raises(ValueError):
        inspect(t, final=True)


@pytest.mark.parametrize("extra", ["slot", "marker", "case", "run", "attempt", "symlink"])
def test_audit_rejects_extra_attempt_hierarchy(top_level, extra):
    t = top_level
    if extra == "marker":
        (t.campaign / "slot-003-started.json").write_text("{}")
    elif extra == "slot":
        (t.campaign / "slots/003").mkdir(parents=True)
    elif extra == "symlink":
        (t.campaign / "slots").symlink_to(t.measurement, target_is_directory=True)
    else:
        relative = "slots/001/trial/cases/"
        relative += {
            "case": "unregistered_case",
            "run": "sheet_metal_nesting/runs/002",
            "attempt": "sheet_metal_nesting/runs/001/attempts/002",
        }[extra]
        (t.campaign / relative).mkdir(parents=True)
    with pytest.raises(ValueError, match="extra|unsafe|linked"):
        inspect(t)


@pytest.mark.parametrize("change", ["denominator", "third_row", "identity"])
def test_audit_rejects_wrong_summary_schedule(top_level, change):
    t = top_level
    if change == "denominator":
        t.summary["planned_attempts"] = 4
    elif change == "third_row":
        t.summary["slots"].append(deepcopy(t.summary["slots"][0]))
    else:
        t.summary["slots"][1]["case_key"] = "sheet_metal_nesting"
    with pytest.raises(ValueError, match="denominator|identity"):
        inspect(t)


def test_audit_refuses_snapshot_that_advances_during_observation(top_level):
    t = top_level
    changed = deepcopy(t.summary)
    changed["slots"][0]["started"] = True
    reads = iter((deepcopy(t.summary), changed))
    t.dispatcher.summarize = lambda: next(reads)
    with pytest.raises(ValueError, match="campaign advanced"):
        inspect(t)


@pytest.fixture
def registration(tmp_path, monkeypatch):
    _actual_adapter, legacy = audit.dependencies()
    measurement = tmp_path / "specs/074-corrected-staged-measurement/measurement"
    campaign = tmp_path / ".lunar/corrected-staged"
    measurement.mkdir(parents=True)
    campaign.mkdir(parents=True)
    historical = ".lunar/real-eval-glm-5.2-high-score-20260909/manifest.json"
    files = {
        "src/famou/fixture.py": b"# frozen source\n",
        "specs/074-corrected-staged-measurement/measurement/worker.py": b"# frozen worker\n",
        "tests/test_measurement074_fixture.py": b"# frozen offline test\n",
        ".lunar/corrected-staged/inputs/profile.json": b"{}\n",
        historical: b'{"kind":"historical_fixture"}\n',
    }
    for relative, raw in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    hashes = {relative: hashlib.sha256(raw).hexdigest() for relative, raw in files.items()}
    manifest = {
        "campaign_id": "fixture-corrected-staged",
        "source_files_sha256": {k: v for k, v in hashes.items() if k.startswith("src/")},
        "frozen_files_sha256": {k: v for k, v in hashes.items()
                                if k.startswith(("specs/", "tests/", ".lunar/corrected-staged/"))},
        "historical_files_sha256": {historical: hashes[historical]},
    }
    raw = legacy.canonical(manifest)
    digest = hashlib.sha256(raw).hexdigest()
    reports = {"manifest.json": raw, **{
        name: legacy.canonical({"passed": True, "model_calls": 0, "manifest_sha256": digest})
        for name in ("prelaunch-audit.json", "dry-run.json")
    }}
    for directory in (measurement, campaign):
        for name, body in reports.items():
            (directory / name).write_bytes(body)
        (directory / "manifest.sha256").write_text(digest + "\n")
    started = {"manifest_sha256": digest, "campaign_id": manifest["campaign_id"],
               "planned_attempts": 2, "concurrency": 2, "registration_commit": "c" * 40,
               "started_unix_seconds": 101.0}
    (campaign / "started.json").write_bytes(legacy.canonical(started))
    calls, git_calls = [], []
    preaudit = SimpleNamespace(**{
        "check_" + name: lambda *args, name=name: calls.append((name, args))
        for name in ("schedule", "source", "frozen", "history", "runtime")
    })

    def load_current(name):
        calls.append(("load", name))
        return preaudit

    adapter = SimpleNamespace(load_current=load_current)
    committed = {**files, **{
        (measurement / name).relative_to(tmp_path).as_posix(): body
        for name, body in reports.items()
    }}

    def git(repo, *args):
        git_calls.append((repo, args))
        assert repo == tmp_path
        if args == ("show", "-s", "--format=%ct", started["registration_commit"]):
            return b"100\n"
        assert args[0] == "show" and args[1].startswith(started["registration_commit"] + ":")
        relative = args[1].split(":", 1)[1]
        if relative not in committed:
            raise subprocess.CalledProcessError(128, ["git", *args])
        return committed[relative]

    monkeypatch.setattr(legacy, "_git", git)
    return SimpleNamespace(
        repo=tmp_path, measurement=measurement, manifest_path=measurement / "manifest.json",
        campaign=campaign, manifest=manifest, digest=digest, started=started, legacy=legacy,
        adapter=adapter, calls=calls, git_calls=git_calls, committed=committed, preaudit=preaudit,
    )


def verify(t):
    evidence = t.legacy.Evidence(t.repo)
    return audit.verify_registration(t.manifest_path, t.campaign, evidence, t.adapter, t.legacy)


def test_registration_checks_frozen_bytes_commit_chain_and_runtime(registration):
    t = registration
    assert verify(t) == (t.manifest, t.digest, t.started)
    assert [name for name, _args in t.calls] == [
        "load", "schedule", "source", "frozen", "history", "runtime",
    ]
    assert t.calls[-1][1] == (t.repo, t.campaign, {"kind": "historical_fixture"})
    expected = {k for k in t.manifest["frozen_files_sha256"] if k.startswith(("specs/", "tests/"))}
    expected |= {(t.measurement / name).relative_to(t.repo).as_posix()
                 for name in ("manifest.json", "prelaunch-audit.json", "dry-run.json")}
    actual = {args[1].split(":", 1)[1] for _repo, args in t.git_calls if len(args) == 2}
    assert actual == expected


@pytest.mark.parametrize("mapping", ["source_files_sha256", "frozen_files_sha256", "historical_files_sha256"])
def test_registration_rejects_changed_bytes_before_loading_wrappers(registration, mapping):
    t = registration
    relative = next(iter(t.manifest[mapping]))
    (t.repo / relative).write_bytes(b"changed frozen evidence")
    with pytest.raises(ValueError, match="frozen evidence changed"):
        verify(t)
    assert t.calls == [] and t.git_calls == []


@pytest.mark.parametrize("prefix", ["specs/", "tests/"])
@pytest.mark.parametrize("change", ["different", "missing"])
def test_registration_refuses_missing_or_different_frozen_commit_bytes(registration, prefix, change):
    t = registration
    relative = next(k for k in t.manifest["frozen_files_sha256"] if k.startswith(prefix))
    if change == "missing":
        del t.committed[relative]
        expected = subprocess.CalledProcessError
    else:
        t.committed[relative] = b"different committed script or test"
        expected = ValueError
    with pytest.raises(expected):
        verify(t)


@pytest.mark.parametrize("name", ["manifest.json", "prelaunch-audit.json", "dry-run.json"])
@pytest.mark.parametrize("change", ["commit", "campaign"])
def test_registration_refuses_uncommitted_or_unmirrored_readiness_reports(registration, name, change):
    t = registration
    if change == "commit":
        t.committed[(t.measurement / name).relative_to(t.repo).as_posix()] = b"different"
    else:
        (t.campaign / name).write_bytes(b"different")
    with pytest.raises(ValueError, match="manifest differ|uncommitted launch evidence"):
        verify(t)


def test_registration_propagates_runtime_version_mismatch(registration):
    t = registration

    def refuse(*args):
        raise ValueError("installed runtime versions differ")

    t.preaudit.check_runtime = refuse
    with pytest.raises(ValueError, match="runtime versions differ"):
        verify(t)


@pytest.mark.parametrize("field,value", [
    ("registration_commit", "not-a-commit"), ("started_unix_seconds", 90.0),
    ("planned_attempts", 4), ("concurrency", 1), ("manifest_sha256", "0" * 64),
])
def test_registration_rejects_startup_binding_or_time(registration, field, value):
    t = registration
    started = {**t.started, field: value}
    (t.campaign / "started.json").write_bytes(t.legacy.canonical(started))
    with pytest.raises(ValueError):
        verify(t)


def report_fixture():
    rows, stages = [], []
    for index, case in enumerate(("sheet_metal_nesting", "china_post_pickup_optimization"), 1):
        rows.append({"index": index, "arm": "S", "budget_arm": "master_1200", "case_key": case,
                     "status": "not_started", "started": False, "process_terminated": False,
                     "subject_receipt_accepted": False, "harness_receipt_accepted": False,
                     "extraction_status": None, "validity_score": None,
                     "overall_score": None, "quality_score": None})
        stages.append({"index": index, "budget_arm": "master_1200", "master_duration_seconds": None,
                       "plan_record_valid": False, "build_entered_observed": False,
                       "build_transcript_present": False, "resume_used": None})
    return {"passed": True, "complete": False, "final_acceptance": False,
            "manifest_sha256": "a" * 64, "stages": stages, "summary": {
                "manifest_sha256": "a" * 64, "planned_attempts": 2,
                "all_slots_terminated": False, "slots": rows, "budget_arms": {
                    "master_1200": {"planned": 2, "started": 0, "terminated": 0, "valid": 0,
                                    "valid_solution_rate": 0, "subject_receipts": 0,
                                    "accepted_harness_receipts": 0},
                },
            }}


def accept_first(fixture):
    fixture["summary"]["slots"][0].update(
        status="completed", started=True, process_terminated=True,
        subject_receipt_accepted=True, harness_receipt_accepted=True,
        extraction_status="completed", validity_score=1, overall_score=1.0185, quality_score=1.0185,
    )
    fixture["stages"][0].update(plan_record_valid=True, build_entered_observed=True,
                                 build_transcript_present=True, resume_used=False)
    fixture["summary"]["budget_arms"]["master_1200"].update(
        started=1, terminated=1, valid=1, valid_solution_rate=0.5,
        subject_receipts=1, accepted_harness_receipts=1,
    )


def test_report_preserves_partial_null_and_valid_above_one_without_adding_history():
    fixture = report_fixture()
    text = report.render_report(fixture)
    assert "进行中，结果仍未决" in text and "null" in text
    assert "固定分母2" in text and "历史样本不进分母" in text
    assert "不是最终失败率" in text
    accept_first(fixture)
    text = report.render_report(fixture)
    assert "1.0185 | 1.0185" in text and "已观察有效解1" in text
    assert "null | null | null" in text


@pytest.mark.parametrize("change", ["no_harness", "uncompleted_extraction", "bool", "nan", "inf"])
def test_report_refuses_unsupported_score_evidence(change):
    fixture = report_fixture()
    accept_first(fixture)
    row = fixture["summary"]["slots"][0]
    if change == "no_harness":
        row["harness_receipt_accepted"] = False
    elif change == "uncompleted_extraction":
        row["extraction_status"] = "failed"
    else:
        row["quality_score"] = {"bool": True, "nan": float("nan"), "inf": float("inf")}[change]
    with pytest.raises(ValueError):
        report.render_report(fixture)


@pytest.mark.parametrize("field,value", [
    ("planned", 4), ("started", 1), ("terminated", 1), ("valid", 1),
    ("valid_solution_rate", 0.5), ("subject_receipts", 1), ("accepted_harness_receipts", 1),
])
def test_report_refuses_group_counts_or_rate_contradicting_rows(field, value):
    fixture = report_fixture()
    fixture["summary"]["budget_arms"]["master_1200"][field] = value
    with pytest.raises(ValueError):
        report.render_report(fixture)


@pytest.mark.parametrize("change", [
    "final", "unearned_final_acceptance", "summary_termination", "numeric_termination",
    "duration", "stage_group", "extra_group", "build_without_plan",
])
def test_report_refuses_unsupported_completion_stage_or_group(change):
    fixture = report_fixture()
    if change == "final":
        fixture["complete"] = True
    elif change == "unearned_final_acceptance":
        fixture["final_acceptance"] = True
    elif change == "summary_termination":
        fixture["summary"]["all_slots_terminated"] = True
    elif change == "numeric_termination":
        fixture["summary"]["slots"][0]["process_terminated"] = 0
    elif change == "duration":
        fixture["stages"][0]["master_duration_seconds"] = 1200
    elif change == "stage_group":
        fixture["stages"][0]["budget_arm"] = "master_300"
    elif change == "extra_group":
        fixture["summary"]["budget_arms"]["master_300"] = {"planned": 2}
    else:
        fixture["stages"][0]["build_entered_observed"] = True
    with pytest.raises(ValueError):
        report.render_report(fixture)


def test_final_report_requires_both_rows_terminated_and_preserves_unknown_scores():
    fixture = report_fixture()
    for row in fixture["summary"]["slots"]:
        row.update(started=True, process_terminated=True,
                   status="terminated_without_accepted_report")
    fixture["summary"]["budget_arms"]["master_1200"].update(started=2, terminated=2)
    fixture["summary"]["all_slots_terminated"] = True
    fixture.update(complete=True, final_acceptance=True)
    text = report.render_report(fixture)
    assert "两个尝试已终止，结果审计通过" in text and "已观察有效解0" in text
    assert text.count("null | null | null") == 2 and "不是最终失败率" not in text
