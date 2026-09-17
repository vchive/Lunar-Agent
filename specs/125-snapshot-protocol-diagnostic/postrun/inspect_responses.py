"""Verify retained 125 bytes and inspect syntax/data only; never execute generated code."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from famou._benchmark_files import read_regular_file
from famou.algorithm import AlgorithmProblemContract
from famou.candidate_evaluation import _format_valid
from famou.evaluator_bundle import _parse_envelope, _parse_probe_suite

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST_SHA = "c76a7f4802ad2691fc0c400c3525f9e38f4c520399a1a6a9f8f8e4506ea43a12"
INVENTORY_SHA = "1e0b9ea9e8551af1458419244b30d3e879476082f3a008ccf94eb73f9cf73121"
PIN_COUNTS = {"product_files": 77, "measurement_files": 14, "historical_files": 91}


def hashed(raw):
    return hashlib.sha256(raw).hexdigest()


def capture_text(raw, index, stage):
    capture = json.loads(raw)
    text = capture["redacted_prefix"]
    encoded = text.encode("utf-8")
    if (type(capture["request_index"]) is not int or capture["request_index"] != index
            or capture["stage_hint"] != stage
            or capture["capture_scope"] != "parsed_assistant_text_only"
            or type(capture["tool_call_count"]) is not int or capture["tool_call_count"] != 0
            or capture["truncated"] is not False
            or capture["redaction_applied"] is not False
            or type(capture["text_utf8_bytes"]) is not int
            or type(capture["redacted_prefix_utf8_bytes"]) is not int
            or len(encoded) != capture["text_utf8_bytes"]
            or len(encoded) != capture["redacted_prefix_utf8_bytes"]
            or hashed(encoded) != capture["text_sha256"]):
        raise ValueError("complete_original_text_unavailable")
    return text, {"text_bytes": len(encoded), "text_sha256": hashed(encoded)}


def probe_summary(suite, contract):
    rows, scores = [], {}
    for index, probe in enumerate(suite.probes, 1):
        files = {item.path: item.content.encode() for item in probe.files}
        root = json.loads(files["data/raw/limit.json"])
        output = json.loads(files["output/result.json"])
        matches = type(root) is dict and type(root.get("limit")) is int and root["limit"] >= 0
        value = output.get("value") if type(output) is dict else None
        validity = int(type(value) is int and 0 <= value <= root["limit"]) if matches else None
        scores[probe.name] = (index, value if validity == 1 else None)
        rows.append({"index": index, "input_root_type": type(root).__name__,
                     "input_structure_matches_contract": matches,
                     "output_schema_valid": _format_valid(contract.outputs[0], files["output/result.json"]),
                     "declared_validity": probe.expected_validity, "oracle_validity": validity,
                     "expected_matches_oracle": validity == probe.expected_validity if matches else None})
    orders = []
    for order in suite.score_order:
        better, worse = scores[order.better], scores[order.worse]
        orders.append({"better_index": better[0], "worse_index": worse[0],
                       "oracle_comparison_holds": better[1] > worse[1]
                       if better[1] is not None and worse[1] is not None else None})
    return {"probes": rows, "score_order": orders}


def source_facts(source):
    """Recognize the retained source's sufficient branch without executing its AST."""
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    for checked in nodes:
        match checked:
            case ast.If(test=ast.Compare(left=ast.Call(func=ast.Name(id="type"), args=[ast.Name(id=input_name)]),
                                         ops=[ast.IsNot()], comparators=[ast.Name(id="int")]),
                        body=[ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id=error_name),
                                                                         attr="append")))]):
                loads = [node for node in nodes if isinstance(node, ast.Assign)
                         and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                         and node.targets[0].id == input_name and isinstance(node.value, ast.Call)
                         and isinstance(node.value.func, ast.Name)]
                readers = [node for node in nodes if isinstance(node, ast.FunctionDef)
                           and any(node.name == loaded.value.func.id for loaded in loads)]
                for reader in readers:
                    returns = [node for node in ast.walk(reader) if isinstance(node, ast.Return)
                               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                               and isinstance(node.value.func.value, ast.Name)
                               and node.value.func.value.id == "json" and node.value.func.attr == "loads"]
                    branches = [node for node in nodes if isinstance(node, ast.If)
                                and isinstance(node.test, ast.Name) and node.test.id == error_name]
                    for branch in branches:
                        reports = [node for node in branch.body if isinstance(node, (ast.Assign, ast.Return))
                                   and isinstance(node.value, ast.Dict)]
                        for report in reports:
                            literals = {key.value: value.value for key, value in zip(report.value.keys, report.value.values)
                                        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
                            invalid = {key: literals.get(key) for key in ("validity", "quality", "combined_score")}
                            if (returns and set(invalid) <= set(literals)
                                    and invalid == {"validity": 0, "quality": None, "combined_score": 0}):
                                loaded = next(node for node in loads if node.value.func.id == reader.name)
                                return {"reader_returns_json_root": True, "input_assigned_whole_reader_return": True,
                                        "input_root_rejected_unless_exact_int": True,
                                        "type_error_appended_to_invalid_branch_condition": True,
                                        "invalid_report_literals": invalid,
                                        "lines": {"reader": reader.lineno, "reader_return": returns[0].lineno,
                                                  "input_assignment": loaded.lineno, "input_type_check": checked.lineno,
                                                  "error_append": checked.body[0].lineno,
                                                  "invalid_branch": branch.lineno, "invalid_report": report.lineno},
                                        "path_key_lines": {key: sorted({node.lineno for node in nodes
                                                           if isinstance(node, ast.Constant) and node.value == key})
                                                           for key in ("target", "path", "limit")}}
    raise ValueError("static_branch_not_established")


def inspect():
    manifest_raw = read_regular_file(HERE.parent / "measurement/manifest.json", 1024 * 1024)
    if hashed(manifest_raw) != MANIFEST_SHA:
        raise ValueError("registration_changed")
    manifest = json.loads(manifest_raw)
    for group, count in PIN_COUNTS.items():
        if len(manifest[group]) != count:
            raise ValueError("registered_file_count_changed")
        for name, digest in manifest[group].items():
            if hashed(read_regular_file(REPO / name, 32 * 1024 * 1024)) != digest:
                raise ValueError("registered_bytes_changed")
    inventory_raw = read_regular_file(HERE / "evidence.json", 1024 * 1024)
    if hashed(inventory_raw) != INVENTORY_SHA:
        raise ValueError("inventory_changed")
    inventory = json.loads(inventory_raw)["files"]
    root = REPO / manifest["campaign_root"]
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("symlinked_retained_evidence")
    if {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} != set(inventory):
        raise ValueError("retained_file_set_changed")
    retained = {}
    for name, descriptor in inventory.items():
        raw = read_regular_file(root / name, 32 * 1024 * 1024)
        if {"size": len(raw), "sha256": hashed(raw)} != descriptor:
            raise ValueError("retained_evidence_changed")
        retained[name] = raw
    captures = [capture_text(retained[f"attempt-001/responses/response-{index:03d}.json"], index, stage)
                for index, stage in ((1, "evaluator_compiler"), (2, "evaluator_auditor"))]
    contract = AlgorithmProblemContract.from_dict(manifest["contract"])
    compiler = _parse_envelope(captures[0][0], contract, invocation="snapshot")
    auditor = _parse_probe_suite(captures[1][0], contract, label="audit", invocation="snapshot")
    worker = json.loads(retained["attempt-001/worker-finished.json"])
    if worker.get("error_class") != "EvaluatorBundleError" or worker.get("frozen") is not None:
        raise ValueError("recorded_outcome_changed")
    return {"schema_version": "1", "analysis": "postrun_static_only_no_evaluator_execution",
            "manifest_sha256": MANIFEST_SHA, "inventory_sha256": INVENTORY_SHA,
            "verified_pins": PIN_COUNTS, "verified_retained_files": len(retained),
            "response_metadata": [capture[1] for capture in captures],
            "native_compiler_and_auditor_parsers": "accepted",
            "compiler": probe_summary(compiler.probe_suite(), contract), "auditor": probe_summary(auditor, contract),
            "source_bytes": len(compiler.evaluator_source.encode()),
            "source_sha256": hashed(compiler.evaluator_source.encode()),
            "source_facts": source_facts(compiler.evaluator_source),
            "recorded_error_class": "EvaluatorBundleError",
            "limits": ["sufficient_static_defect_not_replayed_runtime_trace", "original_preflight_trace_not_retained",
                       "no_generated_source_probe_or_holdout_executed", "raw_integer_input_has_no_contract_oracle",
                       "no_causal_prompt_effect_or_general_correctness_claim"]}


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True, indent=2))
