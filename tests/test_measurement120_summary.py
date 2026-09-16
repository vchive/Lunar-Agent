"""The new campaign can summarize only closed evidence and cannot rerun holdouts."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "specs/120-supported-scope-acceptance/measurement"


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("measurement120_summary", HERE / "campaign.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "HERE", tmp_path / "feature/measurement")
    monkeypatch.setattr(module, "MANIFEST", tmp_path / "manifest.json")
    module.MANIFEST.write_text("{}")
    return module


def test_unfinished_campaign_never_runs_holdouts(campaign, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "source_analysis", SimpleNamespace(
        analyze_slot=lambda *args: calls.append(args),
    ))
    manifest = {"campaign_root": "run"}
    campaign.write_new(campaign.REPO / "run/started.json", {})
    with pytest.raises(ValueError, match="campaign_not_finished"):
        campaign.summarize(manifest)
    assert calls == []


@pytest.mark.parametrize("existing", ["results.json", "evidence.json"])
def test_existing_summary_never_runs_holdouts(campaign, monkeypatch, existing):
    calls = []
    monkeypatch.setitem(sys.modules, "source_analysis", SimpleNamespace(
        analyze_slot=lambda *args: calls.append(args),
    ))
    campaign.write_new(campaign.HERE.parent / "postrun" / existing, {})
    with pytest.raises(ValueError, match="campaign_already_summarized"):
        campaign.summarize({"campaign_root": "run"})
    assert calls == []


def test_failed_process_preserves_denominator_and_nulls_official_quality(campaign, monkeypatch):
    calls = []

    def analyze_slot(root, case_key):
        calls.append(case_key)
        return {"primary_valid_completion": True, "quality": 37, "quality_gap": 0}

    monkeypatch.setitem(sys.modules, "source_analysis", SimpleNamespace(analyze_slot=analyze_slot))
    manifest = {
        "campaign_root": "run", "campaign_id": "offline", "product_commit": "offline",
        "planned_attempts": 2, "limits": campaign.LIMITS, "limitations": [],
        "schedule": [{"index": i, "case_key": key, "attempt_id": f"slot-{i}"}
                     for i, key in enumerate(campaign.CASES, 1)],
    }
    campaign.write_new(campaign.REPO / "run/started.json",
                       {"manifest_sha256": campaign.sha(campaign.MANIFEST)})
    campaign.write_new(campaign.REPO / "run/finished.json", {"status": "finished"})
    result = campaign.summarize(manifest)
    saved = json.loads((campaign.HERE.parent / "postrun/results.json").read_text())
    assert calls == list(campaign.CASES)
    assert result["planned_attempts"] == 2
    assert saved["valid_completions"] == saved["registered_valid_completions"] == 0
    assert all(s["quality"] is None and s["quality_gap"] is None for s in saved["slots"])
    assert all(s["delivery_completion"] for s in saved["slots"])
    assert all(s["usage"]["usage_complete"] is False for s in saved["slots"])
