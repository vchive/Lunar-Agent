"""Consume one registered slot with native automatic solve and conditional holdouts."""
from __future__ import annotations

import contextlib
import json
import os
import time

from analysis import verified_preparation
from campaign import CAMPAIGN_ID, MANIFEST, REPO, canonical, sha, verify, write_new
from case import GOAL, INPUT_BYTES, audit_holdouts
from observation import RuntimeGuard, load_provider, observed_guard


def _error_class(exc):
    for cls in (OSError, ValueError, TypeError, RuntimeError):
        if isinstance(exc, cls):
            return cls.__name__
    return "Exception"


def main():
    started = time.monotonic()
    manifest = verify(committed=True)
    root = REPO / manifest["campaign_root"]
    slot = root / "attempt-001"
    for path in (root / "started.json", slot / "started.json"):
        marker = json.loads(path.read_text())
        if marker.get("manifest_sha256") != sha(MANIFEST) or marker.get("campaign_id") != CAMPAIGN_ID:
            raise ValueError("attempt_not_started")
    if (root / "finished.json").exists() or (slot / "finished.json").exists():
        raise ValueError("attempt_already_finished")
    write_new(slot / "worker-started.json", {"manifest_sha256": sha(MANIFEST), "index": 1})
    guard, stage, rows = None, "setup", []
    result = {"status": "failed", "stage": stage, "frozen": None, "holdouts": rows,
              "native_exit_code": None, "solve_error_class": None,
              "preparation_error_class": None, "error_class": None}
    try:
        inputs = slot / "inputs"
        inputs.mkdir(mode=0o700)
        with (inputs / "limit.json").open("xb") as stream:
            os.chmod(stream.name, 0o600)
            stream.write(INPUT_BYTES)
            stream.flush()
            os.fsync(stream.fileno())
        if (manifest["goal"] != GOAL or manifest["input_utf8"] != INPUT_BYTES.decode()
                or sha(inputs / "limit.json") != manifest["input_sha256"]):
            raise ValueError("registered_input_or_goal_changed")
        model = manifest["provider"]["requested_model"]
        provider = load_provider(requested_model=model, expected=manifest["provider"])
        limits, population = manifest["limits"], manifest["population"]
        remaining = limits["wall_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("attempt_deadline_reached")
        guard = RuntimeGuard(provider, model, slot / "calls.jsonl", max_requests=limits["max_requests"],
                             token_stop_threshold=limits["token_stop_threshold"], wall_seconds=remaining,
                             request_seconds=limits["request_seconds"])

        def continuation():
            # Model admission stays stopped independently. These local snapshots use
            # no provider requests and may inspect a previously verified preparation.
            if time.monotonic() - started >= limits["wall_seconds"]:
                raise ValueError("acceptance_continuation_stopped")

        args = ["solve", GOAL, "--evolve", "--multi-file",
                "--workspace", str(slot / "workspace"), "--home", str(slot / "home"),
                "--runtime", "openai-compatible", "--model", model, "--agent-loop",
                "--max-steps", str(manifest["runtime_options"]["max_steps"]), "--workers", "1",
                "--population-size", str(population["size"]),
                "--offspring-per-iteration", str(population["offspring_per_iteration"]),
                "--islands", str(population["islands"]), "--max-rounds", str(population["max_rounds"]),
                "--stagnation-rounds", str(population["stagnation_rounds"]),
                "--seed", str(population["seed"]), "--timeout", str(limits["candidate_seconds"]),
                "--evaluator-preparation-timeout", str(limits["preparation_request_seconds"]),
                "--evaluator-preparation-wall-timeout", str(limits["preparation_wall_seconds"]),
                "--json", "--input", str(inputs / "limit.json")]
        from famou.cli import main as native_main

        stage = "solve"
        try:
            with observed_guard(guard), (slot / "cli.json").open("x") as stream:
                os.chmod(stream.name, 0o600)
                with contextlib.redirect_stdout(stream):
                    result["native_exit_code"] = native_main(args)
        except Exception as exc:  # noqa: BLE001 - failed candidates may still leave verified preparation
            result["solve_error_class"] = _error_class(exc)
        stage = "preparation_check"
        try:
            contract, bundle = verified_preparation(slot)
        except Exception as exc:  # noqa: BLE001 - no preparation fallback, replay or repair
            result["preparation_error_class"] = _error_class(exc)
        else:
            frozen = {
                "fingerprint": bundle.fingerprint, "contract_sha256": bundle.contract_sha256,
                "input_profile_sha256": bundle.input_profile_sha256,
                "files": {path.name: sha(path) for path in sorted(bundle.root.iterdir())},
            }
            result["frozen"] = frozen
            write_new(slot / "frozen.json", frozen)
            stage = "holdouts"

            def record(row):
                write_new(slot / "holdouts" / f"{len(rows) + 1:03d}.json", row)
                rows.append(row)

            audit_holdouts(bundle, contract, slot / "holdout-workspaces", timeout=limits["holdout_seconds"],
                           continuation_guard=continuation, record=record)
            continuation()
            if result["native_exit_code"] == 0 and result["solve_error_class"] is None:
                result.update(status="completed", stage="finished")
            else:
                result["stage"] = "solve"
        if result["frozen"] is None:
            result["stage"] = "preparation_check"
    except Exception as exc:  # noqa: BLE001 - never retain generated exception prose in public status
        result.update(status="failed", stage=stage, error_class=_error_class(exc))
    result.update(guard=guard.snapshot() if guard is not None else None,
                  elapsed_seconds=max(0, time.monotonic() - started))
    write_new(slot / "worker-finished.json", result)
    print(canonical({"status": result["status"], "stage": result["stage"],
                     "native_exit_code": result["native_exit_code"],
                     "frozen": result["frozen"] is not None,
                     "holdouts_executed": sum(row["snapshot_started"] for row in rows)}), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
