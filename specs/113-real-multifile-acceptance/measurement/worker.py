"""Stage one registered public task and invoke the unchanged native solve CLI once."""
from __future__ import annotations

import contextlib
import json
import sys
import time

from campaign import REPO, canonical, sha, verify, write_new
from runtime_guard import RuntimeGuard, installed_guard, load_provider


def main(index):
    started = time.monotonic()
    manifest = verify(committed=True)
    slot = next(item for item in manifest["schedule"] if item["index"] == index)
    root = REPO / manifest["campaign_root"]
    slot_root = root / slot["attempt_id"]
    receipt = json.loads((root / "started.json").read_text())
    from campaign import MANIFEST
    slot_marker = json.loads((slot_root / "started.json").read_text())
    if (receipt.get("manifest_sha256") != sha(MANIFEST)
            or receipt.get("campaign_id") != manifest["campaign_id"]
            or receipt.get("schedule") != manifest["schedule"]
            or any(slot_marker.get(key) != value for key, value in slot.items())
            or slot_marker.get("manifest_sha256") != sha(MANIFEST)
            or (root / "finished.json").exists() or (slot_root / "finished.json").exists()):
        raise ValueError("slot_not_started")
    # Claim before loading credentials. Any setup failure consumes this planned slot.
    write_new(slot_root / "worker-started.json", {"index": index})
    guard = None
    try:
        case = manifest["cases"][slot["case_key"]]
        inputs = slot_root / "inputs"
        inputs.mkdir()
        for filename, payload in case["inputs"].items():
            write_new(inputs / filename, payload)
        model = manifest["provider"]["requested_model"]
        provider = load_provider(requested_model=model, expected=manifest["provider"])
        limits, population = manifest["limits"], manifest["population"]
        remaining = limits["wall_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("attempt_deadline_reached")
        guard = RuntimeGuard(provider, model, slot_root / "calls.jsonl",
                             max_requests=limits["max_requests"],
                             token_stop_threshold=limits["token_stop_threshold"],
                             wall_seconds=remaining,
                             request_seconds=limits["request_seconds"])
        args = ["solve", case["goal"], "--evolve", "--multi-file",
                "--workspace", str(slot_root / "workspace"), "--home", str(slot_root / "home"),
                "--runtime", "openai-compatible", "--model", model, "--agent-loop",
                "--max-steps", str(limits["tool_steps_per_invocation"]), "--workers", "1",
                "--population-size", str(population["size"]),
                "--offspring-per-iteration", str(population["offspring_per_iteration"]),
                "--islands", str(population["islands"]), "--max-rounds", str(population["max_rounds"]),
                "--stagnation-rounds", str(population["stagnation_rounds"]),
                "--seed", str(population["seed"]), "--timeout", str(limits["request_seconds"]), "--json"]
        for filename in case["inputs"]:
            args.extend(["--input", str(inputs / filename)])
        from famou.cli import main as native_main
        with installed_guard(guard), (slot_root / "cli.json").open("x") as stream, contextlib.redirect_stdout(stream):
            code = native_main(args)
        result = {"status": "returned", "exit_code": code, "guard": guard.snapshot()}
    except Exception as exc:  # noqa: BLE001 - fixed diagnostic never includes provider prose
        code = 2
        result = {"status": "worker_failed", "error_type": type(exc).__name__,
                  "guard": guard.snapshot() if guard is not None else None}
    write_new(slot_root / "worker-finished.json", result)
    print(canonical(result), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1])))
