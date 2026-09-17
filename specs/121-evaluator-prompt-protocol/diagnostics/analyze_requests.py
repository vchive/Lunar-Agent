"""Read-only reconstruction of frozen 120 request bytes; emit metadata only.

Run from any directory with Python 3.11 or later. This extracts the registered product's source
from local Git into a temporary directory, verifies every file against its registration,
and invokes only prompt/profile builders. It never loads provider configuration, calls
a model, executes a candidate, or writes into a campaign evidence directory.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REGISTRATION = "specs/120-supported-scope-acceptance/measurement/manifest.json"
REGISTRATION_SHA256 = "d8dd67c250161aed751ebf85ae10f330b03c8eedfaeb7356011e4e4ff7f7270e"
EVIDENCE_MANIFEST = "specs/120-supported-scope-acceptance/postrun/evidence.json"
EVIDENCE_MANIFEST_SHA256 = "4183a2c452a70216042f8522c5ce255b62ae826fe070283f6ff0e6d552c1fa0f"
EVIDENCE_MANIFEST_COMMIT = "566fbb6b9ec58850f0658fde7b3e3215a7666ba5"
CRITICAL_SOURCE_FILES = (
    "src/famou/agent_loop.py", "src/famou/algorithm.py",
    "src/famou/automatic_solve_bundle.py", "src/famou/conversational.py",
    "src/famou/data_profile.py", "src/famou/evaluator_bundle.py",
    "src/famou/evolution.py", "src/famou/http_transport.py", "src/famou/runtime.py",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def registration():
    raw = (REPO / REGISTRATION).read_bytes()
    if sha(raw) != REGISTRATION_SHA256:
        raise ValueError("registration_mismatch")
    return json.loads(raw)


def evidence_inventory(manifest):
    raw = (REPO / EVIDENCE_MANIFEST).read_bytes()
    if sha(raw) != EVIDENCE_MANIFEST_SHA256:
        raise ValueError("evidence_manifest_mismatch")
    inventory = json.loads(raw)
    if inventory["root"] != manifest["campaign_root"]:
        raise ValueError("evidence_root_mismatch")
    return inventory["files"]


def read_evidence(path, campaign_root, inventory, observed):
    name = path.relative_to(campaign_root).as_posix()
    expected = inventory.get(name)
    if expected is None:
        raise ValueError("evidence_file_unregistered")
    with path.open("rb") as stream:
        raw = stream.read(expected["size"] + 1)
    if len(raw) != expected["size"] or sha(raw) != expected["sha256"]:
        raise ValueError("evidence_file_mismatch")
    observed[path.relative_to(REPO).as_posix()] = expected["sha256"]
    return raw


def request_body(prompt, system, model):
    # Same key insertion order, separators and encoding as the registered native runtime.
    return json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")


def reconstruct(source):
    sys.path.insert(0, str(source))
    from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
    from famou.algorithm import AlgorithmProblemContract
    from famou.conversational import RuntimeContractCompiler
    from famou.evaluator_bundle import (
        _build_input_profile,
        _compiler_prompt,
        _output_constraint_ids,
    )
    from famou.evolution import CandidateInputArtifact

    manifest = registration()
    inventory = evidence_inventory(manifest)
    campaign_root = REPO / manifest["campaign_root"]
    rows = []
    evidence = {}

    def read(path):
        return read_evidence(path, campaign_root, inventory, evidence)

    for slot in manifest["schedule"]:
        root = REPO / manifest["campaign_root"] / slot["attempt_id"]
        workspace = root / "workspace"
        calls = [json.loads(line) for line in read(root / "calls.jsonl").splitlines()]
        started = [row for row in calls if row["kind"] == "request_started"]
        finished = [row for row in calls if row["kind"] == "request_finished"]
        if ([row["index"] for row in started] != [1, 2]
                or [row["index"] for row in finished] != [1, 2]):
            raise ValueError("unexpected_request_sequence")
        contract = AlgorithmProblemContract.from_dict(
            json.loads(read(workspace / "solve/contract.json")),
        )
        inputs = []
        for item in sorted(contract.inputs, key=lambda item: item.path):
            raw = read(workspace / "data/raw" / item.path)
            inputs.append(CandidateInputArtifact("data/raw/" + item.path, len(raw), sha(raw)))
        profile = _build_input_profile(workspace, contract, tuple(inputs))
        context = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        profile_context = json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2)
        prompts = (
            RuntimeContractCompiler._prompt(manifest["cases"][slot["case_key"]]["goal"], None),
            _compiler_prompt(contract, profile, invocation="snapshot"),
        )
        requests = []
        for index, (prompt, start, finish) in enumerate(zip(prompts, started, finished), 1):
            body = request_body(prompt, ISOLATED_SYSTEM_PROMPT, manifest["provider"]["requested_model"])
            if sha(body) != start["request_sha256"]:
                raise ValueError("request_reconstruction_mismatch")
            requests.append({
                "index": index,
                "stage": "contract_compiler" if index == 1 else "evaluator_compiler",
                "request_sha256": sha(body), "recorded_hash_matches": True,
                "request_body_utf8_bytes": len(body),
                "user_prompt_utf8_bytes": len(prompt.encode("utf-8")),
                "system_prompt_utf8_bytes": len(ISOLATED_SYSTEM_PROMPT.encode("utf-8")),
                "request_fields": ["model", "messages", "stream"],
                "message_roles": ["system", "user"], "tool_count": 0, "stream": False,
                "timeout_seconds": start["request_timeout_seconds"],
                "elapsed_seconds": finish["elapsed_seconds"],
                "outcome": finish["outcome"], "failure_reason": finish["failure_reason"],
                "response_status": finish["response_status"], "observation": finish["observation"],
                "usage": finish["usage"],
            })
        # Read only bounded capture metadata into the report; never retain its text prefix.
        response = json.loads(read(root / "responses/response-001.json"))
        output_constraints = _output_constraint_ids(contract, "snapshot")
        rows.append({
            "case_key": slot["case_key"], "attempt_id": slot["attempt_id"],
            "requests": requests,
            "unique_request_hashes": len({row["request_sha256"] for row in started}),
            "evaluator_context": {
                "contract_utf8_bytes": len(context.encode("utf-8")),
                "contract_occurrences": prompts[1].count(context),
                "profile_utf8_bytes": len(profile_context.encode("utf-8")),
                "profile_occurrences": prompts[1].count(profile_context),
                "output_hard_constraint_count": len(output_constraints),
                "source_hard_constraint_count": len(contract.hard_constraints) - len(output_constraints),
                "minimum_synthetic_probe_count": len(output_constraints) + 2,
            },
            "completed_contract_response": {
                "text_utf8_bytes": response["text_utf8_bytes"],
                "text_sha256": response["text_sha256"],
                "capture_truncated": response["truncated"],
                "capture_redaction_applied": response["redaction_applied"],
            },
        })
    return {
        "schema_version": "1", "analysis": "offline_frozen_request_reconstruction",
        "campaign_id": manifest["campaign_id"], "registration_sha256": REGISTRATION_SHA256,
        "evidence_manifest_sha256": EVIDENCE_MANIFEST_SHA256,
        "evidence_manifest_commit": EVIDENCE_MANIFEST_COMMIT,
        "product_commit": manifest["product_commit"], "model_requests_made": 0,
        "source": "local_git_product_snapshot_verified_against_registration",
        "source_sha256": {name: manifest["product_files"][name] for name in CRITICAL_SOURCE_FILES},
        "evidence_sha256": dict(sorted(evidence.items())), "tasks": rows,
        "findings": [
            "All four reconstructed request bodies match recorded SHA-256 digests exactly.",
            "Each request has exactly one isolated system message and one user message; no tools or history are sent.",
            "Each evaluator prompt contains its contract and structural input profile once.",
            "Request bodies omit temperature, max_tokens, reasoning_effort and response_format.",
            "Native application and campaign guard issue no retry after either timeout.",
            "Both evaluator calls reached the local 600-second deadline with phase open_response and no observed HTTP status.",
        ],
        "limits": [
            "Request hashes identify locally constructed bodies; they do not prove provider receipt or execution.",
            "open_response covers process startup, connection and waiting for response headers; it does not identify the remote cause.",
            "Redirects, proxy behavior, gateway retries, queue time and model generation time are not separately observed.",
            "Nonstreaming requests provide no partial model progress; timed-out response length, usage and cost remain unknown.",
            "Byte counts are not token counts and do not establish context overflow or a timeout cause.",
            "The configured provider's reasoning effort is not sent in these native request bodies; provider defaults remain uncontrolled.",
            "Reported output tokens and captured assistant text do not establish a reasoning-token breakdown.",
        ],
    }


def extract_product(manifest, target):
    archived = subprocess.check_output(
        ["git", "archive", "--format=zip", manifest["product_commit"], "src"], cwd=REPO,
    )
    pinned = {name: value for name, value in manifest["product_files"].items() if name.startswith("src/")}
    with zipfile.ZipFile(io.BytesIO(archived)) as source:
        files = [info for info in source.infolist() if not info.is_dir()]
        if {info.filename for info in files} != set(pinned):
            raise ValueError("product_file_set_mismatch")
        for info in files:
            name = Path(info.filename)
            if name.is_absolute() or any(part in {".", ".."} for part in name.parts):
                raise ValueError("product_path_invalid")
            raw = source.read(info)
            if sha(raw) != pinned[info.filename]:
                raise ValueError("product_bytes_mismatch")
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--frozen-source":
        print(json.dumps(reconstruct(Path(sys.argv[2])), ensure_ascii=False, sort_keys=True, indent=2))
        return
    if len(sys.argv) != 1:
        raise ValueError("unexpected_arguments")
    manifest = registration()
    evidence_inventory(manifest)
    with tempfile.TemporaryDirectory(prefix="lunar121-frozen-product-") as temporary:
        target = Path(temporary)
        extract_product(manifest, target)
        environment = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}}
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--frozen-source", str(target / "src")],
            cwd=target, env=environment, check=True, capture_output=True, text=True,
        )
        # Fail closed if an import unexpectedly emits non-JSON text.
        result = json.loads(completed.stdout)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - retained prompt/response text must never reach stdout.
        raise SystemExit("offline_request_analysis_failed") from None
