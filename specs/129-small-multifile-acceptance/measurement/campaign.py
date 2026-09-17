"""Register, run once and read-only summarize native small multi-file acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from case import GOAL, INPUT_BYTES, holdouts
from observation import load_provider
from supervision import supervise

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST = HERE / "manifest.json"
PRODUCT_COMMIT = "b9518570a18e25ad784d00ba864a18ee8e30ac80"
CAMPAIGN_ID = "acceptance129-glm-5.2-small-multifile-20260917"
LIMITS = {"request_seconds": 600, "wall_seconds": 2400, "max_requests": 20,
          "token_stop_threshold": 160000, "holdout_seconds": 5}
REFERENCE = REPO / "specs/128-format-admission-diagnostic/measurement/manifest.json"
REFERENCE_SHA = "460da2cedd52c9cf4774139df084129685c1bd686372f2662c5c683421d59a48"
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
    previous = json.loads(REFERENCE.read_text())
    if (INPUT_BYTES.decode() != previous["input_utf8"]
            or holdouts() != previous["holdouts"]):
        raise ValueError("prior_mathematics_changed")
    return {
        "schema_version": "1", "campaign_id": CAMPAIGN_ID,
        "campaign_root": ".lunar/" + CAMPAIGN_ID, "product_commit": PRODUCT_COMMIT,
        "provider": previous["provider"], "limits": dict(LIMITS),
        "goal": GOAL, "goal_sha256": hashlib.sha256(GOAL.encode()).hexdigest(),
        "input_utf8": INPUT_BYTES.decode(), "input_sha256": hashlib.sha256(INPUT_BYTES).hexdigest(),
        "holdouts": holdouts(), "planned_attempts": 1,
        "schedule": [{"index": 1, "attempt_id": "attempt-001"}],
        "retries_or_replacements": 0, "concurrency": 1,
        "population": {"size": 2, "offspring_per_iteration": 1, "islands": 1,
                       "max_rounds": 1, "stagnation_rounds": 3, "seed": 129},
        "runtime_options": {
            "runtime": "openai-compatible", "entrypoint": "solve --evolve --multi-file",
            "model": "glm-5.2", "agent_loop": True, "max_steps": 4, "workers": 1,
            "max_retries": 1, "memory": False, "session_history": False, "allow_exec": False,
            "preparation_message_roles": ["system", "user"], "preparation_tools": 0,
            "preparation_history": False, "generated_contract": True,
            "evaluator_invocation": "snapshot", "terminal_resume": False,
        },
        "sampling": {"stream": False, "temperature": None, "max_tokens": None,
                     "reasoning_effort": None, "response_format": None,
                     "policy": "native_omissions_provider_defaults_uncontrolled"},
        "primary": "verified source-aware feasible parent delivery / 1 planned attempt",
        "secondary": "exact registered snapshot agreement / 8 planned holdouts",
        "joint": "verified feasible parent delivery and 8 of 8 holdouts and cleanup / 1 planned attempt",
        "known_optimum": 3, "failure_quality": None, "cost_micros": None,
        "official_quality_requires": "primary_delivery_completed_worker_zero_exit_verified_cleanup",
        "holdout_continuation": "verified_preparation_and_remaining_wall_independent_of_model_request_stop",
        "response_capture": {"scope": "parsed_assistant_text_only", "max_prefix_bytes": 65536,
                             "private": True, "credential_redacted": True},
        "local_failure_capture": {
            "source": "validated_durable_native_preparation_status",
            "keys": ["schema_version", "stage", "reason", "probe_index", "input_index", "order_index"],
            "missing_or_invalid_capture": None, "effect_on_outcome": "none",
        },
        "reference_preparation": {
            "campaign_id": previous["campaign_id"], "manifest_sha256": REFERENCE_SHA,
            "product_commit": previous["product_commit"],
        },
        "limitations": ["small_synthetic_task_not_general_acceptance", "no_causal_or_webagent_claim",
                        "python_file_count_does_not_prove_helper_use_or_input_read",
                        "holdouts_do_not_cover_all_bool_float_rules", "no_os_sandbox",
                        "holdouts_not_in_model_context_but_locally_accessible",
                        "observed_token_threshold_not_server_cap", "unknown_timeout_usage",
                        "local_milestones_not_provider_execution_telemetry"],
    }


def pins(paths):
    return {p.relative_to(REPO).as_posix(): sha(p) for p in sorted(set(paths))}


def measurement_paths():
    return [*HERE.glob("*.py"), *(HERE.parent / name for name in
            ("spec.md", "plan.md", "quickstart.md")), SHARED_GUARD,
            *REPO.glob("tests/test_measurement129_*.py")]


def historical_paths():
    return [p for number in (113, 115, 117, 120, 121, 122, 123, 124, 125, 126, 127, 128)
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
