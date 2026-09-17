"""Static postrun diagnosis uses independent fixtures and never runs generated code."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from famou import evaluator_bundle
from famou.algorithm import AlgorithmProblemContract

INSPECTOR = (Path(__file__).resolve().parents[1]
             / "specs/125-snapshot-protocol-diagnostic/postrun/inspect_responses.py")
PRIVATE = "private-fixture-detail"
SOURCE = '''import json
import sys
from pathlib import Path

def read_payload(location):
    return json.loads(Path(location).read_text())

def main():
    request = read_payload(sys.argv[1])
    incoming = next(item for item in request["inputs"] if item["target"] == "limit.json")
    bound = read_payload(Path("inputs") / incoming["target"])
    outgoing = next(item for item in request["outputs"] if item["path"] == "output/result.json")
    chosen = read_payload(outgoing["path"])["value"]
    issues = []
    if type(bound) is not int:
        issues.append({"code": "valid-value", "message": "private-fixture-detail"})
    if issues:
        return {"schema_version": "1", "evaluator_id": "compiled-bundle",
                "validity": 0, "quality": None, "combined_score": 0,
                "detailed_scores": {}, "error_info": issues}
    return {"schema_version": "1", "evaluator_id": "compiled-bundle",
            "validity": 1, "quality": chosen, "combined_score": chosen,
            "detailed_scores": {}, "error_info": []}

if __name__ == "__main__":
    print(json.dumps(main()))
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


@pytest.fixture
def inspector():
    spec = importlib.util.spec_from_file_location("diagnostic125_static_fixture", INSPECTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def contract():
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "independent-static-fixture",
        "problem_type": "continuous", "statement": "Choose an integer between zero and limit.",
        "inputs": [{"path": "limit.json", "format": "json", "fields": {"limit": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [{"id": "valid-value", "description": "Integer 0 <= value <= limit.",
                              "source": "explicit_assumption", "verification": "independent"}],
        "soft_constraints": [], "success_criteria": ["Largest valid integer."],
        "deliverables": ["output/result.json"], "assumptions": [],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
    })


def payload(*, object_input, compiler=False):
    probes = []
    for index, value in enumerate((0, 3, 4), 1):
        probes.append({
            "name": f"fixture-{index}", "constraint_id": None if value <= 3 else "valid-value",
            "expected_validity": int(value <= 3),
            "files": [
                {"path": "data/raw/limit.json", "content": json.dumps({"limit": 3} if object_input else 3)},
                {"path": "output/result.json", "content": json.dumps({"value": value})},
            ],
        })
    value = {"schema_version": "1", "constraint_coverage": ["valid-value"], "probes": probes,
             "score_order": [{"better": "fixture-2", "worse": "fixture-1"}]}
    if compiler:
        value.update(objective=PRIVATE, evaluator_source=SOURCE)
    return value


def captured(text, index=1, stage="evaluator_compiler"):
    return {
        "schema_version": "1", "request_index": index, "stage_hint": stage,
        "capture_scope": "parsed_assistant_text_only", "tool_call_count": 0,
        "text_utf8_bytes": len(text.encode()), "text_sha256": sha(text.encode()),
        "redacted_prefix": text, "redacted_prefix_utf8_bytes": len(text.encode()),
        "truncated": False, "redaction_applied": False,
    }


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("static diagnosis attempted model or evaluator execution")

    for name in ("compile_evaluator_bundle", "_preflight", "_snapshot_probe"):
        monkeypatch.setattr(evaluator_bundle, name, forbidden)
    monkeypatch.setattr("famou.candidate_execution_runner._bounded_process_bytes", forbidden)
    monkeypatch.setattr("famou.runtime.OpenAICompatibleRuntime.complete", forbidden)
    monkeypatch.setattr("famou.agent_loop.AgentLoopRuntime.run_isolated", forbidden)
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)


def test_capture_requires_complete_original_text_without_disclosing_it(inspector):
    text = PRIVATE + " 中文"
    raw = encoded(captured(text))
    actual, metadata = inspector.capture_text(raw, 1, "evaluator_compiler")
    assert actual == text
    assert PRIVATE not in json.dumps(metadata)


@pytest.mark.parametrize("mutation", ["truncated", "redacted", "text_hash", "text_bytes", "prefix_bytes",
                                      "request_index", "stage", "scope", "tool_calls", "bool_index"])
def test_incomplete_or_misbound_capture_is_rejected(inspector, mutation):
    capture = captured(PRIVATE)
    if mutation == "truncated":
        capture["truncated"] = True
    elif mutation == "redacted":
        capture["redaction_applied"] = True
    elif mutation == "text_hash":
        capture["text_sha256"] = "0" * 64
    elif mutation == "text_bytes":
        capture["text_utf8_bytes"] += 1
    elif mutation == "prefix_bytes":
        capture["redacted_prefix_utf8_bytes"] += 1
    elif mutation == "request_index":
        capture["request_index"] = 2
    elif mutation == "stage":
        capture["stage_hint"] = "evaluator_auditor"
    elif mutation == "scope":
        capture["capture_scope"] = "raw_http_body"
    elif mutation == "bool_index":
        capture["request_index"] = True
    else:
        capture["tool_call_count"] = 1
    with pytest.raises(ValueError):
        inspector.capture_text(encoded(capture), 1, "evaluator_compiler")


@pytest.mark.parametrize("object_input", [False, True], ids=["compiler-scalar", "auditor-object"])
def test_probe_analysis_checks_declared_structure_and_exact_oracle_without_execution(
    inspector, contract, no_execution, object_input,
):
    text = json.dumps(payload(object_input=object_input, compiler=not object_input))
    parser = evaluator_bundle._parse_probe_suite if object_input else evaluator_bundle._parse_envelope
    suite = parser(text, contract, invocation="snapshot")
    report = inspector.probe_summary(suite, contract)
    assert len(report["probes"]) == 3
    assert all(row["input_structure_matches_contract"] is object_input for row in report["probes"])
    assert all(row["output_schema_valid"] for row in report["probes"])
    assert PRIVATE not in json.dumps(report)
    if object_input:
        assert [row["oracle_validity"] for row in report["probes"]] == [1, 1, 0]
        assert all(row["expected_matches_oracle"] for row in report["probes"])
        assert report["score_order"] == [{"better_index": 2, "worse_index": 1,
                                           "oracle_comparison_holds": True}]


@pytest.fixture
def retained_fixture(inspector, contract, monkeypatch, tmp_path):
    """All bytes are new fixtures; no real manifest, private response or slot is read."""
    here = tmp_path / "specs/fixture/postrun"
    here.mkdir(parents=True)
    pins = {}
    for group in ("product_files", "measurement_files", "historical_files"):
        path = tmp_path / "pins" / (group + ".txt")
        path.parent.mkdir(exist_ok=True)
        path.write_text("independent fixture " + group)
        pins[group] = {path.relative_to(tmp_path).as_posix(): sha(path.read_bytes())}
    manifest = {**pins, "campaign_root": ".lunar/independent-static-fixture",
                "contract": contract.to_dict()}
    manifest_path = here.parent / "measurement/manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_bytes(encoded(manifest))
    root = tmp_path / manifest["campaign_root"]
    contents = {
        "attempt-001/responses/response-001.json": captured(json.dumps(payload(object_input=False, compiler=True))),
        "attempt-001/responses/response-002.json": captured(json.dumps(payload(object_input=True)), 2, "evaluator_auditor"),
        "attempt-001/worker-finished.json": {"error_class": "EvaluatorBundleError", "frozen": None},
    }
    for name, content in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded(content))
    monkeypatch.setattr(inspector, "HERE", here)
    monkeypatch.setattr(inspector, "REPO", tmp_path)
    monkeypatch.setattr(inspector, "MANIFEST_SHA", sha(manifest_path.read_bytes()))
    monkeypatch.setattr(inspector, "PIN_COUNTS", {group: 1 for group in pins})

    def bind_inventory():
        files = {path.relative_to(root).as_posix(): {"size": len(path.read_bytes()), "sha256": sha(path.read_bytes())}
                 for path in root.rglob("*") if path.is_file()}
        raw = encoded({"schema_version": "1", "files": files})
        (here / "evidence.json").write_bytes(raw)
        monkeypatch.setattr(inspector, "INVENTORY_SHA", sha(raw))

    bind_inventory()
    return inspector, manifest_path, root, bind_inventory


def test_full_static_inspection_verifies_independent_bytes_without_execution(retained_fixture, no_execution):
    inspector, _manifest, _root, _bind = retained_fixture
    report = inspector.inspect()
    assert report["verified_pins"] == {"product_files": 1, "measurement_files": 1, "historical_files": 1}
    assert report["verified_retained_files"] == 3
    assert report["native_compiler_and_auditor_parsers"] == "accepted"
    assert report["source_sha256"] == sha(SOURCE.strip().encode())
    assert report["source_bytes"] == len(SOURCE.strip().encode())
    assert report["recorded_error_class"] == "EvaluatorBundleError"
    assert all(row["input_structure_matches_contract"] is False for row in report["compiler"]["probes"])
    assert all(row["input_structure_matches_contract"] is True for row in report["auditor"]["probes"])
    public = json.dumps(report)
    for private in (PRIVATE, "read_payload", "bound", "issues", "fixture-1"):
        assert private not in public
    facts = report["source_facts"]
    assert facts["input_root_rejected_unless_exact_int"] is True
    assert facts["reader_returns_json_root"] is True
    assert facts["invalid_report_literals"] == {"validity": 0, "quality": None, "combined_score": 0}
    assert facts["path_key_lines"]["limit"] == []


@pytest.mark.parametrize("mutation,reason", [
    ("manifest", "registration_changed"), ("inventory", "inventory_changed"),
    ("pin", "registered_bytes_changed"), ("pin_count", "registered_file_count_changed"),
    ("capture", "retained_evidence_changed"), ("extra_file", "retained_file_set_changed"),
    ("missing_file", "retained_file_set_changed"), ("symlink", "symlinked_retained_evidence"),
    ("incomplete_text", "complete_original_text_unavailable"), ("worker", "recorded_outcome_changed"),
])
def test_bound_static_evidence_rejects_changed_or_incomplete_inputs(
    retained_fixture, monkeypatch, no_execution, mutation, reason,
):
    inspector, manifest, root, bind_inventory = retained_fixture
    response = root / "attempt-001/responses/response-001.json"
    if mutation == "manifest":
        manifest.write_bytes(manifest.read_bytes() + b" ")
    elif mutation == "inventory":
        path = inspector.HERE / "evidence.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "pin":
        (inspector.REPO / "pins/product_files.txt").write_text("changed product fixture")
    elif mutation == "pin_count":
        monkeypatch.setattr(inspector, "PIN_COUNTS", {**inspector.PIN_COUNTS, "product_files": 2})
    elif mutation == "capture":
        response.write_bytes(response.read_bytes() + b" ")
    elif mutation == "extra_file":
        (root / "unexpected").write_text("unregistered bytes")
    elif mutation == "missing_file":
        response.unlink()
    elif mutation == "symlink":
        (root / "unexpected-link").symlink_to(response)
    elif mutation == "incomplete_text":
        value = json.loads(response.read_bytes())
        value["truncated"] = True
        response.write_bytes(encoded(value))
        bind_inventory()
    else:
        (root / "attempt-001/worker-finished.json").write_bytes(encoded({
            "error_class": "private-fixture-detail", "frozen": None,
        }))
        bind_inventory()
    with pytest.raises(ValueError, match=reason):
        inspector.inspect()


def test_static_branch_facts_follow_structure_after_identifier_and_line_changes(inspector, no_execution):
    source = "\n\n" + SOURCE.replace("read_payload", "decode_document").replace("bound", "ceiling").replace("issues", "failures")
    facts = inspector.source_facts(source)
    assert facts["input_assigned_whole_reader_return"] is True
    assert facts["type_error_appended_to_invalid_branch_condition"] is True
    assert "decode_document" not in json.dumps(facts)
    assert facts["lines"]["reader"] > 6


@pytest.mark.parametrize("old,new", [
    ('return json.loads(Path(location).read_text())', 'return json.loads(Path(location).read_text())["limit"]'),
    ('type(bound) is not int', 'type(bound) is int'),
    ('"validity": 0, "quality": None, "combined_score": 0', '"validity": 1, "quality": 1, "combined_score": 1'),
    ('"validity": 0, "quality": None, "combined_score": 0', '"validity": 0, "combined_score": 0'),
])
def test_unestablished_static_branch_is_not_claimed(inspector, no_execution, old, new):
    with pytest.raises(ValueError, match="static_branch_not_established"):
        inspector.source_facts(SOURCE.replace(old, new))
