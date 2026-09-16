"""One fixed, failure-preserving real-model acceptance campaign. Reuses immutable task, guard and analysis helpers."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

SHARED = Path(__file__).resolve().parents[2] / "113-real-multifile-acceptance/measurement"
sys.path.append(str(SHARED))

from task_scope import CASES
from tasks import holdouts, optimum

if Path(sys.modules["tasks"].__file__).resolve() != SHARED / "tasks.py":
    raise ValueError("shared_tasks_module_mismatch")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST = HERE / "manifest.json"
PRODUCT_COMMIT = "c5695088c83bf69188bd7ae222056c8b63233656"
CAMPAIGN_ID = "acceptance120-glm-5.2-supported-scope-20260917"
LIMITS = {"wall_seconds": 3600, "request_seconds": 600, "max_requests": 16,
          "token_stop_threshold": 160000, "tool_steps_per_invocation": 4}
REFERENCE = HERE.parents[1] / "117-extended-deadline-acceptance/measurement"
REFERENCE_SHA256 = "822d46f6cc9bfd0850129bf4455bd32eb4652b7f9a07f3dabe9b4a8066b43ec2"
FIXED_FIELDS = ("provider", "holdouts", "optima", "population",
                "runtime_options", "sampling", "schedule", "planned_attempts", "concurrency",
                "retries_or_replacements", "failure_quality", "cost_micros")
PRIMARY = "verified source-aware delivery with registered hard Python file count and independently feasible outputs / 2 planned attempts"


def shared_module(name):
    module = importlib.import_module(name)
    if Path(module.__file__).resolve() != SHARED / (name + ".py"):
        raise ValueError("shared_module_mismatch")
    return module


def check_fixed_conditions(payload):
    reference_path = REFERENCE / "manifest.json"
    if sha(reference_path) != REFERENCE_SHA256:
        raise ValueError("historical_registration_changed")
    reference = json.loads(reference_path.read_text())
    if any(payload.get(key) != reference[key] for key in FIXED_FIELDS):
        raise ValueError("fixed_conditions_changed")
    expected_limits = reference["limits"]
    if payload.get("limits") != expected_limits or LIMITS != expected_limits:
        raise ValueError("fixed_conditions_changed")
    if payload.get("cases") != CASES or payload.get("primary") != PRIMARY:
        raise ValueError("fixed_conditions_changed")
    if set(CASES) != set(reference["cases"]) or any(
        {k: v for k, v in CASES[key].items() if k != "goal"}
        != {k: v for k, v in reference["cases"][key].items() if k != "goal"}
        for key in CASES
    ):
        raise ValueError("fixed_conditions_changed")
    if payload.get("condition_changes") != condition_changes(reference):
        raise ValueError("condition_changes_invalid")
    if (payload.get("product_commit") != PRODUCT_COMMIT
            or payload.get("campaign_id") != CAMPAIGN_ID
            or payload.get("campaign_root") != ".lunar/" + CAMPAIGN_ID
            or payload.get("previous_campaign") != reference["campaign_id"]):
        raise ValueError("campaign_identity_changed")


def condition_changes(reference):
    return {
        "product_commit": {"before": reference["product_commit"], "after": PRODUCT_COMMIT},
        "task_goals": {"before": {k: v["goal"] for k, v in reference["cases"].items()},
                       "after": {k: v["goal"] for k, v in CASES.items()}},
        "primary": {"before": reference["primary"], "after": PRIMARY},
    }


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(UTC).isoformat()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
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


def file_pins(paths):
    return {p.relative_to(REPO).as_posix(): sha(p) for p in sorted(paths)}


def prepare():
    load_provider = shared_module("runtime_guard").load_provider
    if MANIFEST.exists():
        raise ValueError("registration_already_exists")
    product = [REPO / p for p in git("ls-files", "src", "pyproject.toml").splitlines()]
    for path in product:
        expected = subprocess.check_output(["git", "show", f"{PRODUCT_COMMIT}:{path.relative_to(REPO)}"], cwd=REPO)
        if path.read_bytes() != expected:
            raise ValueError("product_changed_before_registration")
    provider = load_provider(requested_model="glm-5.2")
    measurement = [*HERE.glob("*.py"), *(HERE.parent / name for name in
                                       ("spec.md", "plan.md", "quickstart.md")),
                   *REPO.glob("tests/test_measurement120_*.py"),
                   *(SHARED / name for name in ("tasks.py", "runtime_guard.py", "analyze.py")),
                   *REPO.glob("tests/test_measurement113_*.py")]
    payload = {
        "schema_version": "1", "campaign_id": CAMPAIGN_ID, "registered_utc": utc(),
        "product_commit": PRODUCT_COMMIT, "product_files": file_pins(product),
        "measurement_files": file_pins(measurement), "runtime": runtime_identity(),
        "provider": provider.safe_metadata("glm-5.2"), "limits": LIMITS,
        "historical_files": file_pins([
            *SHARED.parent.rglob("*.md"), *SHARED.glob("*.py"), SHARED / "manifest.json",
            *SHARED.parent.glob("postrun/*.json"),
            *REFERENCE.parent.rglob("*.md"), *REFERENCE.glob("*.py"),
            REFERENCE / "manifest.json", *REFERENCE.parent.glob("postrun/*.json"),
            *REPO.glob("tests/test_measurement117_*.py"),
            *REPO.glob("specs/115-isolated-intake-acceptance/**/*.md"),
            *REPO.glob("specs/115-isolated-intake-acceptance/measurement/*.py"),
            *REPO.glob("specs/115-isolated-intake-acceptance/measurement/*.json"),
            *REPO.glob("specs/115-isolated-intake-acceptance/postrun/*.json"),
            *REPO.glob("tests/test_measurement115_*.py"),
        ]),
        "previous_campaign": "acceptance117-glm-5.2-extended-deadline-20260916",
        "condition_changes": condition_changes(json.loads((REFERENCE / "manifest.json").read_text())),
        "response_diagnostics": {"retained_utf8_bytes": 65536, "credential_redacted": True,
                                 "private_only": True, "affects_native_outcome": False},
        "campaign_root": ".lunar/" + CAMPAIGN_ID,
        "schedule": [{"index": i, "case_key": key, "attempt_id": f"slot-{i:03d}-attempt-001"}
                     for i, key in enumerate(CASES, 1)],
        "planned_attempts": 2, "concurrency": 1, "retries_or_replacements": 0,
        "cases": CASES, "holdouts": {key: holdouts(key) for key in CASES},
        "optima": {key: optimum(key, case["inputs"]) for key, case in CASES.items()},
        "population": {"size": 2, "offspring_per_iteration": 1, "islands": 1,
                       "max_rounds": 1, "stagnation_rounds": 3, "seed": 113},
        "runtime_options": {"agent_loop": True, "allow_exec": False, "memory": False,
                            "session_history": False, "workers": 1, "max_retries": 1},
        "sampling": {"temperature": None, "max_tokens": None, "reasoning_effort": None,
                     "policy": "native_request_omits_parameters_provider_defaults_uncontrolled"},
        "failure_quality": None, "cost_micros": None,
        "primary": PRIMARY,
        "limitations": ["two_hand_authored_tasks_one_attempt_each", "no_normal_or_webagent_control",
                        "product_and_task_scope_changed_not_a_causal_comparison",
                        "file_count_does_not_prove_imports_dependencies_or_input_reading",
                        "empty_lowercase_py_files_count_toward_requirement",
                        "observed_token_threshold_not_server_token_cap", "no_os_sandbox",
                        "holdout_sources_not_supplied_as_context_but_locally_accessible",
                        "evaluator_probe_agreement_not_general_business_correctness"],
    }
    check_fixed_conditions(payload)
    write_new(MANIFEST, payload)
    return {"status": "registered", "manifest_sha256": sha(MANIFEST), "planned_attempts": 2,
            "model_calls": 0}


def verify(*, committed=False):
    manifest = json.loads(MANIFEST.read_text())
    check_fixed_conditions(manifest)
    tracked = set(git("ls-files", "src", "pyproject.toml").splitlines())
    disk_python = {path.relative_to(REPO).as_posix() for path in (REPO / "src").rglob("*.py")}
    if (tracked != set(manifest["product_files"])
            or disk_python != {name for name in tracked if name.startswith("src/") and name.endswith(".py")}):
        raise ValueError("product_file_set_changed")
    for group in ("product_files", "measurement_files", "historical_files"):
        for relative, expected in manifest[group].items():
            path = REPO / relative
            if path.is_symlink() or sha(path) != expected:
                raise ValueError("registration_bytes_changed")
    if manifest["runtime"] != runtime_identity():
        raise ValueError("runtime_changed")
    if manifest["cases"] != CASES or manifest["holdouts"] != {key: holdouts(key) for key in CASES}:
        raise ValueError("case_definitions_changed")
    if committed:
        for group in ("product_files", "measurement_files", "historical_files"):
            for relative in manifest[group]:
                if subprocess.check_output(["git", "show", "HEAD:" + relative], cwd=REPO) != (REPO / relative).read_bytes():
                    raise ValueError("registered_file_not_committed")
        relative = MANIFEST.relative_to(REPO).as_posix()
        if subprocess.check_output(["git", "show", "HEAD:" + relative], cwd=REPO) != MANIFEST.read_bytes():
            raise ValueError("registration_not_committed")
        # The user's normal push instruction also makes preregistration reviewable remotely.
        if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
            raise ValueError("registration_not_pushed")
    return manifest


def clean_environment():
    # No provider credential, PYTHONPATH or ambient Famou setting enters child processes.
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8", "FAMOU_MAX_RETRIES": "1",
            "FAMOU_RUNTIME_TIMEOUT": str(LIMITS["request_seconds"])}


def process_table():
    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,pgid=,stat="], text=True,
                                   timeout=3)
    return {int(a): (int(b), int(c), state)
            for a, b, c, state in (line.split() for line in rows.splitlines())}


def descendants(pid, table):
    result, todo = set(), [pid]
    while todo:
        parent = todo.pop()
        children = {child for child, (ppid, _, _) in table.items() if ppid == parent} - result
        result.update(children)
        todo.extend(children)
    return result


def stop_process_tree(process, observed=None):
    # Retain observed group ownership after a worker exits and its children are reparented.
    # This is bounded best-effort cleanup of observed descendants, not an OS sandbox.
    table = process_table()
    owned = {} if observed is None else dict(observed)
    owned.update({pid: table[pid][1] for pid in descendants(process.pid, table) | {process.pid}
                  if pid in table})
    alive = {pid for pid, group in owned.items()
             if pid in table and table[pid][1] == group and not table[pid][2].startswith("Z")}
    groups = {owned[pid] for pid in alive}
    groups.discard(os.getpgrp())
    for group in groups:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
    deadline = time.monotonic() + 1
    while True:
        remaining = process_table()
        live = sorted(pid for pid, group in owned.items() if pid in remaining
                      and remaining[pid][1] == group and not remaining[pid][2].startswith("Z"))
        if not live or time.monotonic() >= deadline:
            return live
        time.sleep(0.02)


def supervise(command, slot_root, wall_seconds):
    started = time.monotonic()
    with (slot_root / "stdout.log").open("xb") as out, (slot_root / "stderr.log").open("xb") as err:
        process = subprocess.Popen(command, cwd=REPO, env=clean_environment(),
                                   stdout=out, stderr=err, start_new_session=True)
        cleanup, observed, error_type = [], {}, None
        deadline = started + wall_seconds
        try:
            while True:
                table = process_table()
                observed.update({pid: table[pid][1]
                                 for pid in descendants(process.pid, table) | {process.pid}
                                 if pid in table})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timed_out"
                    break
                try:
                    process.wait(timeout=min(0.2, remaining))
                    status = "exited" if time.monotonic() < deadline else "timed_out"
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException as exc:  # noqa: BLE001 - cleanup is mandatory after interruption
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "supervisor_failed"
            error_type = type(exc).__name__
        try:
            cleanup = stop_process_tree(process, observed)
            cleanup_verified = not cleanup
        except Exception as exc:  # noqa: BLE001 - unknown cleanup must block the next slot
            cleanup_verified = False
            error_type = type(exc).__name__
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        code = process.returncode
    return {"process_status": status, "exit_code": code,
            "elapsed_seconds": time.monotonic() - started, "remaining_observed_pids": cleanup,
            "cleanup_verified": cleanup_verified, "error_type": error_type}


def run_slots(manifest, root, runner=supervise):
    root.mkdir(parents=True, exist_ok=False)
    write_new(root / "started.json", {"campaign_id": manifest["campaign_id"],
              "manifest_sha256": sha(MANIFEST), "started_utc": utc(),
              "registration_commit": git("rev-parse", "HEAD"), "schedule": manifest["schedule"]})
    campaign_status, started_attempts = "finished", 0
    for slot in manifest["schedule"]:
        slot_root = root / slot["attempt_id"]
        slot_root.mkdir()
        write_new(slot_root / "started.json", {**slot, "started_utc": utc(),
                                              "manifest_sha256": sha(MANIFEST)})
        started_attempts += 1
        try:
            result = runner([sys.executable, str(HERE / "worker.py"), str(slot["index"])],
                            slot_root, manifest["limits"]["wall_seconds"])
        except BaseException as exc:  # noqa: BLE001 - retain interrupted attempts without retry
            result = {"process_status": "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit))
                      else "supervisor_failed", "error_type": type(exc).__name__,
                      "elapsed_seconds": None, "exit_code": None, "cleanup_verified": False,
                      "remaining_observed_pids": []}
        write_new(slot_root / "finished.json", {**result, "finished_utc": utc()})
        print(canonical({"slot": slot["index"], "case_key": slot["case_key"], **result}), flush=True)
        if (result.get("cleanup_verified") is not True or result.get("remaining_observed_pids")
                or result.get("process_status") in {"interrupted", "supervisor_failed"}):
            campaign_status = "stopped_before_remaining_slots"
            break
    write_new(root / "finished.json", {"finished_utc": utc(), "status": campaign_status,
              "planned_attempts": manifest["planned_attempts"], "started_attempts": started_attempts})
    return {"status": campaign_status, "root": str(root), "planned_attempts": manifest["planned_attempts"],
            "started_attempts": started_attempts}


def usage_summary(path):
    rows, malformed = [], False
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise TypeError("journal row must be an object")
                rows.append(row)
            except (TypeError, ValueError):
                malformed = True
    starts, ends = {}, {}
    known = {key: 0 for key in ("input_tokens", "output_tokens", "total_tokens")}
    for row in rows:
        index, kind = row.get("index"), row.get("kind")
        if type(index) is not int or index <= 0:
            malformed = True
        elif kind == "request_started" and index == len(starts) + 1:
            starts[index] = row
        elif kind == "request_finished" and index in starts and index not in ends:
            usage = row.get("usage")
            if usage is not None and (
                not isinstance(usage, dict) or set(usage) != set(known)
                or any(type(value) is not int or value < 0 for value in usage.values())
                or usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]
            ):
                malformed, usage = True, None
            ends[index] = {**row, "usage": usage}
            if usage is not None:
                for key, value in usage.items():
                    known[key] += value
        else:
            malformed = True
    complete = (path.exists() and not malformed and set(starts) == set(ends)
                and all(row.get("usage") is not None for row in ends.values()))
    return {"provider_requests": len(starts), "finished_requests": len(ends),
            "known_usage": known, "usage_complete": complete, "cost_micros": None,
            "journal_malformed": malformed, "pending_requests": sorted(set(starts) - set(ends)),
            "request_outcomes": [{key: row.get(key) for key in
                                  ("index", "outcome", "elapsed_seconds", "response_model",
                                   "failure_reason", "response_status")} for row in ends.values()]}


def summarize(manifest):
    from source_analysis import analyze_slot
    root = REPO / manifest["campaign_root"]
    postrun = HERE.parent / "postrun"
    if (postrun / "results.json").exists() or (postrun / "evidence.json").exists():
        raise ValueError("campaign_already_summarized")
    if not (root / "started.json").exists():
        raise ValueError("campaign_not_started")
    if not (root / "finished.json").exists():
        raise ValueError("campaign_not_finished")
    receipt = json.loads((root / "started.json").read_text())
    if receipt.get("manifest_sha256") != sha(MANIFEST):
        raise ValueError("campaign_registration_mismatch")
    slots = []
    for slot in manifest["schedule"]:
        slot_root = root / slot["attempt_id"]
        result = analyze_slot(slot_root, slot["case_key"])
        result["delivery_completion"] = bool(result["primary_valid_completion"])
        result.update(slot)
        finished = slot_root / "finished.json"
        result["process"] = (json.loads(finished.read_text()) if finished.exists() else {
            "process_status": "interrupted_or_unfinished" if (slot_root / "started.json").exists()
            else "not_started", "exit_code": None, "cleanup_verified": False,
        })
        result["usage"] = usage_summary(slot_root / "calls.jsonl")
        worker = slot_root / "worker-finished.json"
        result["worker"] = json.loads(worker.read_text()) if worker.exists() else None
        guard = result["worker"].get("guard") if isinstance(result["worker"], dict) else None
        result["measurement_envelope_verified"] = bool(
            result["process"].get("process_status") == "exited"
            and result["process"].get("exit_code") == 0
            and result["process"].get("cleanup_verified") is True
            and not result["process"].get("remaining_observed_pids")
            and isinstance(result["worker"], dict) and result["worker"].get("status") == "returned"
            and result["worker"].get("exit_code") == 0 and isinstance(guard, dict)
            and guard.get("stopped_reason") is None and guard.get("usage_complete") is True
            and result["usage"]["usage_complete"]
            and guard.get("provider_requests") == result["usage"]["provider_requests"]
            and guard.get("finished_requests") == result["usage"]["finished_requests"]
            and guard.get("known_usage") == result["usage"]["known_usage"]
            and result["usage"]["provider_requests"] <= manifest["limits"]["max_requests"]
            and result["usage"]["known_usage"]["total_tokens"] < manifest["limits"]["token_stop_threshold"]
        )
        result["guard_stop"] = guard.get("stopped_reason") if isinstance(guard, dict) else None
        if (result["process"].get("process_status") != "exited"
                or result["process"].get("exit_code") != 0
                or not isinstance(result["worker"], dict)
                or result["worker"].get("status") != "returned"
                or result["worker"].get("exit_code") != 0):
            result["primary_valid_completion"] = False
            result["quality"] = None
            result["quality_gap"] = None
        result["registered_valid_completion"] = bool(
            result["primary_valid_completion"] and result["measurement_envelope_verified"]
        )
        slots.append(result)
    result = {"schema_version": "1", "campaign_id": manifest["campaign_id"],
              "manifest_sha256": sha(MANIFEST), "product_commit": manifest["product_commit"],
              "planned_attempts": manifest["planned_attempts"],
              "campaign_finished": (root / "finished.json").exists(),
              "valid_completions": sum(bool(slot["primary_valid_completion"]) for slot in slots),
              "registered_valid_completions": sum(bool(slot["registered_valid_completion"]) for slot in slots),
              "slots": slots, "limitations": manifest["limitations"]}
    evidence = {p.relative_to(root).as_posix(): {"size": p.stat().st_size, "sha256": sha(p)}
                for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()
                and "audit" not in p.relative_to(root).parts}
    write_new(postrun / "results.json", result)
    write_new(postrun / "evidence.json", {"root": manifest["campaign_root"], "files": evidence})
    return {"status": "summarized", "valid_completions": result["valid_completions"],
            "planned_attempts": manifest["planned_attempts"], "results": str(postrun / "results.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "run", "summarize"))
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare()
    else:
        manifest = verify(committed=args.action == "run")
        if args.action == "run":
            result = run_slots(manifest, REPO / manifest["campaign_root"])
        elif args.action == "summarize":
            result = summarize(manifest)
        else:
            result = {"status": "verified", "manifest_sha256": sha(MANIFEST), "model_calls": 0}
    print(canonical(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - never publish provider-bearing exception prose
        print(canonical({"status": "rejected", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
