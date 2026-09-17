"""Register, run once and read-only summarize one evaluator-preparation diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from case import INPUT_BYTES, contract, holdouts, stage_inputs
from observation import load_provider
from supervision import supervise

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST = HERE / "manifest.json"
PRODUCT_COMMIT = "519fea5ca70ac1ede3df356ee7391112801ab45d"
CAMPAIGN_ID = "diagnostic123-glm-5.2-small-evaluator-20260917"
LIMITS = {"request_seconds": 600, "wall_seconds": 1320, "max_requests": 2,
          "token_stop_threshold": 160000, "holdout_seconds": 5}
REFERENCE = REPO / "specs/120-supported-scope-acceptance/measurement/manifest.json"
REFERENCE_SHA = "d8dd67c250161aed751ebf85ae10f330b03c8eedfaeb7356011e4e4ff7f7270e"
SHARED_GUARD = REPO / "specs/113-real-multifile-acceptance/measurement/runtime_guard.py"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(UTC).isoformat()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def runtime_identity():
    import famou
    return {"python": str(Path(sys.executable).resolve()),
            "python_sha256": sha(Path(sys.executable).resolve()),
            "python_version": platform.python_version(), "platform": platform.platform(),
            "famou_module": str(Path(famou.__file__).resolve())}


def fixed_conditions():
    if sha(REFERENCE) != REFERENCE_SHA:
        raise ValueError("historical_registration_changed")
    with tempfile.TemporaryDirectory(prefix="lunar123-profile-") as directory:
        _, profile = stage_inputs(Path(directory).resolve())
    from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
    from famou.evaluator_bundle import _compiler_prompt
    body = json.dumps({"model": "glm-5.2", "messages": [
        {"role": "system", "content": ISOLATED_SYSTEM_PROMPT},
        {"role": "user", "content": _compiler_prompt(contract(), profile, invocation="snapshot")},
    ], "stream": False}, ensure_ascii=False).encode()
    return {
        "schema_version": "1", "campaign_id": CAMPAIGN_ID,
        "campaign_root": ".lunar/" + CAMPAIGN_ID, "product_commit": PRODUCT_COMMIT,
        "provider": json.loads(REFERENCE.read_text())["provider"], "limits": dict(LIMITS),
        "contract": contract().to_dict(), "contract_sha256": contract().digest(),
        "input_utf8": INPUT_BYTES.decode(), "input_sha256": hashlib.sha256(INPUT_BYTES).hexdigest(),
        "input_profile": profile, "holdouts": holdouts(), "planned_attempts": 1,
        "compiler_request": {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
        "schedule": [{"index": 1, "attempt_id": "attempt-001"}],
        "retries_or_replacements": 0, "concurrency": 1,
        "runtime_options": {"runtime": "AgentLoopRuntime.run_isolated", "invocation": "snapshot",
                            "message_roles": ["system", "user"], "tools": 0, "history": False,
                            "contract_compiler": False, "solver": False, "source_checks": False},
        "sampling": {"stream": False, "temperature": None, "max_tokens": None,
                     "reasoning_effort": None, "response_format": None,
                     "policy": "native_omissions_provider_defaults_uncontrolled"},
        "primary": "verified evaluator freeze / 1 planned preparation",
        "secondary": "exact registered snapshot agreement / 8 planned holdouts",
        "joint": "verified freeze and 8 of 8 snapshot agreement / 1 planned preparation",
        "failure_quality": None, "cost_micros": None,
        "response_capture": {"scope": "parsed_assistant_text_only", "max_prefix_bytes": 65536,
                             "private": True, "credential_redacted": True},
        "limitations": ["small_synthetic_task_not_original120_tasks", "no_causal_latency_claim",
                        "no_solver_delivery_or_source_behavior", "no_os_sandbox",
                        "holdouts_not_in_model_context_but_locally_accessible",
                        "observed_token_threshold_not_server_cap", "unknown_timeout_usage",
                        "local_milestones_not_provider_execution_telemetry"],
    }


def pins(paths):
    return {p.relative_to(REPO).as_posix(): sha(p) for p in sorted(set(paths))}


def measurement_paths():
    return [*HERE.glob("*.py"), *(HERE.parent / name for name in
            ("spec.md", "plan.md", "quickstart.md")), SHARED_GUARD,
            *REPO.glob("tests/test_measurement123_*.py")]


def historical_paths():
    return [p for number in (113, 115, 117, 120, 121, 122)
            for p in REPO.glob(f"specs/{number}-*/**/*")
            if p.is_file() and p.suffix in {".md", ".json", ".py"}]


def prepare():
    if MANIFEST.exists():
        raise ValueError("registration_already_exists")
    fixed = fixed_conditions()
    provider = load_provider(requested_model="glm-5.2", expected=fixed["provider"])
    assert provider.safe_metadata("glm-5.2") == fixed["provider"]
    product = [REPO / p for p in git("ls-files", "src", "pyproject.toml").splitlines()]
    for path in product:
        raw = subprocess.check_output(["git", "show", f"{PRODUCT_COMMIT}:{path.relative_to(REPO)}"], cwd=REPO)
        if path.read_bytes() != raw:
            raise ValueError("product_changed")
    write_new(MANIFEST, {**fixed, "registered_utc": utc(), "runtime": runtime_identity(),
                        "product_files": pins(product), "measurement_files": pins(measurement_paths()),
                        "historical_files": pins(historical_paths())})
    return {"status": "registered", "manifest_sha256": sha(MANIFEST), "model_calls": 0}


def verify(*, committed=False):
    manifest = json.loads(MANIFEST.read_text())
    fixed = fixed_conditions()
    if (set(manifest) != set(fixed) | {"registered_utc", "runtime", "product_files", "measurement_files", "historical_files"}
            or any(manifest.get(key) != value for key, value in fixed.items())):
        raise ValueError("fixed_conditions_changed")
    tracked = set(git("ls-files", "src", "pyproject.toml").splitlines())
    disk = {p.relative_to(REPO).as_posix() for p in (REPO / "src").rglob("*.py")}
    if (set(manifest["product_files"]) != tracked
            or disk != {p for p in tracked if p.startswith("src/") and p.endswith(".py")}):
        raise ValueError("product_file_set_changed")
    if manifest["runtime"] != runtime_identity():
        raise ValueError("runtime_changed")
    if set(manifest["measurement_files"]) != {p.relative_to(REPO).as_posix() for p in measurement_paths()}:
        raise ValueError("measurement_file_set_changed")
    if set(manifest["historical_files"]) != {p.relative_to(REPO).as_posix() for p in historical_paths()}:
        raise ValueError("historical_file_set_changed")
    for group in ("product_files", "measurement_files", "historical_files"):
        for name, digest in manifest[group].items():
            path = REPO / name
            if path.is_symlink() or sha(path) != digest:
                raise ValueError("registered_bytes_changed")
            if committed and subprocess.check_output(["git", "show", "HEAD:" + name], cwd=REPO) != path.read_bytes():
                raise ValueError("registered_bytes_not_committed")
    if committed:
        if subprocess.check_output(["git", "show", "HEAD:" + MANIFEST.relative_to(REPO).as_posix()], cwd=REPO) != MANIFEST.read_bytes():
            raise ValueError("manifest_not_committed")
        if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
            raise ValueError("registration_not_pushed")
    return manifest


def run(manifest, runner=supervise):
    root = REPO / manifest["campaign_root"]
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    identity = {"campaign_id": CAMPAIGN_ID, "manifest_sha256": sha(MANIFEST),
                "registration_commit": git("rev-parse", "HEAD")}
    write_new(root / "started.json", {**identity, "started_utc": utc()})
    slot = root / "attempt-001"
    slot.mkdir(mode=0o700)
    write_new(slot / "started.json", {**identity, "index": 1})
    started = time.monotonic()
    try:
        result = runner([sys.executable, str(HERE / "worker.py")], slot, manifest["limits"]["wall_seconds"])
    except BaseException as exc:  # noqa: BLE001 - preserve consumed slot without publishing prose
        result = {"process_status": "supervisor_failed", "exit_code": None, "cleanup_verified": False,
                  "remaining_observed_pids": [], "elapsed_seconds": max(0, time.monotonic() - started),
                  "error_type": type(exc).__name__}
    write_new(slot / "finished.json", result)
    final = {**identity, "finished_utc": utc(), "planned_attempts": 1,
             "status": "finished" if result.get("cleanup_verified") else "cleanup_unverified"}
    write_new(root / "finished.json", final)
    return final


def summarize(manifest):
    from analysis import summarize as analyze
    return analyze(manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify", "run", "summarize"))
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare()
    else:
        manifest = verify(committed=args.action == "run")
        result = {"status": "verified", "manifest_sha256": sha(MANIFEST)} if args.action == "verify" else (
            run(manifest) if args.action == "run" else summarize(manifest)
        )
    print(canonical(result))


if __name__ == "__main__":
    main()
