"""Verify retained bytes and statically inspect123; never execute the generated evaluator."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

from famou import evaluator_bundle
from famou.candidate_evaluation import _format_valid
from famou.candidate_execution import CandidateExecutionInput

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST_SHA = "9d05c7d95eb427f60d7be7a93dbfb8c7c53ec50904169e0391053292315f60a7"
RESPONSE = "attempt-001/responses/response-001.json"


def hashed(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    manifest_raw = (HERE.parent / "measurement/manifest.json").read_bytes()
    if hashed(manifest_raw) != MANIFEST_SHA:
        raise ValueError("registration_changed")
    manifest = json.loads(manifest_raw)
    for group in ("product_files", "measurement_files", "historical_files"):
        for name, digest in manifest[group].items():
            if hashed((REPO / name).read_bytes()) != digest:
                raise ValueError("registered_bytes_changed")
    inventory = json.loads((HERE / "evidence.json").read_text())
    raw = (REPO / manifest["campaign_root"] / RESPONSE).read_bytes()
    if {"size": len(raw), "sha256": hashed(raw)} != inventory["files"][RESPONSE]:
        raise ValueError("response_evidence_changed")
    capture = json.loads(raw)
    text = capture["redacted_prefix"]
    if (capture["truncated"] or capture["redaction_applied"]
            or len(text.encode()) != capture["text_utf8_bytes"]
            or hashed(text.encode()) != capture["text_sha256"]):
        raise ValueError("complete_original_text_unavailable")
    spec = importlib.util.spec_from_file_location("_diagnostic123_static_case", HERE.parent / "measurement/case.py")
    case = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(case)
    envelope = evaluator_bundle._parse_envelope(text, case.contract(), invocation="snapshot")
    tree = ast.parse(envelope.evaluator_source)
    mismatches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.comparators) != 1 or len(node.ops) != 1:
            continue
        call, expected = node.left, node.comparators[0]
        if (isinstance(node.ops[0], ast.Eq) and isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute) and call.func.attr == "get"
                and len(call.args) == 1 and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "path" and isinstance(expected, ast.Constant)
                and expected.value == "limit.json"):
            mismatches.append({"line": node.lineno, "lookup_key": "path", "expected_target": "limit.json"})
    probes = []
    for index, probe in enumerate(envelope.probes, 1):
        files = {f.path: f.content.encode() for f in probe.files}
        limit = json.loads(files["data/raw/limit.json"])["limit"]
        value = json.loads(files["output/result.json"])["value"]
        probes.append({"index": index, "expected_validity": probe.expected_validity,
                       "oracle_validity": int(type(value) is int and 0 <= value <= limit),
                       "output_schema_valid": _format_valid(case.contract().outputs[0], files["output/result.json"])})
    report = {
        "schema_version": "1", "analysis": "postrun_static_only_no_evaluator_execution",
        "manifest_sha256": MANIFEST_SHA, "response_text_sha256": capture["text_sha256"],
        "response_text_bytes": len(text.encode()), "source_bytes": len(envelope.evaluator_source.encode()),
        "strict_envelope_source_probe_validation": "accepted", "probe_static_checks": probes,
        "native_input_descriptor_fields": sorted(CandidateExecutionInput("limit.json", "synthetic_probe", 12, "a" * 64).to_dict()),
        "generated_input_lookup_mismatch": mismatches,
        "runtime_prompt_has_exact_input_descriptor_fields": all(
            key in evaluator_bundle._snapshot_invocation_prompt()
            for key in ("source_label", '"target"')
        ),
        "limits": ["static_diagnosis_does_not_replay_or_reclassify_attempt",
                   "no_generated_program_or_holdout_executed_by_this_analysis",
                   "does_not_identify_previous120_transport_timeout_cause"],
    }
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
