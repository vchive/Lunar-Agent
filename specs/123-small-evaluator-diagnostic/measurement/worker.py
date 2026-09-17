"""One native compile/audit/freeze and conditional snapshot diagnostic, never a solver."""
from __future__ import annotations

import json
import time

from campaign import CAMPAIGN_ID, MANIFEST, REPO, canonical, sha, verify, write_new
from case import audit_holdouts, contract, stage_inputs
from observation import RuntimeGuard, load_provider, observed_guard

from famou.agent_loop import AgentLoopRuntime
from famou.evaluator_bundle import compile_evaluator_bundle
from famou.runtime import OpenAICompatibleRuntime


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
    result = {"status": "failed", "stage": stage, "frozen": None, "holdouts": rows}
    try:
        workspace = slot / "workspace"
        inputs, profile = stage_inputs(workspace)
        if profile != manifest["input_profile"] or contract().to_dict() != manifest["contract"]:
            raise ValueError("registered_input_or_contract_changed")
        write_new(slot / "contract.json", contract().to_dict())
        write_new(slot / "input-profile.json", profile)
        provider = load_provider(requested_model="glm-5.2", expected=manifest["provider"])
        limits = manifest["limits"]
        remaining = limits["wall_seconds"] - (time.monotonic() - started)
        guard = RuntimeGuard(provider, "glm-5.2", slot / "calls.jsonl", max_requests=limits["max_requests"],
                             token_stop_threshold=limits["token_stop_threshold"], wall_seconds=remaining,
                             request_seconds=limits["request_seconds"])

        def continuation():
            if guard.stopped_reason is not None or time.monotonic() - started >= limits["wall_seconds"]:
                raise ValueError("diagnostic_continuation_stopped")

        stage = "preparation"
        write_new(slot / "preparation-started.json", {"stage": stage})
        with observed_guard(guard):
            runtime = AgentLoopRuntime(OpenAICompatibleRuntime(), max_steps=4)
            bundle = compile_evaluator_bundle(runtime, contract(), workspace, inputs=inputs,
                                              timeout=limits["request_seconds"], invocation="snapshot",
                                              continuation_guard=continuation)
        frozen = {"fingerprint": bundle.fingerprint, "contract_sha256": bundle.contract_sha256,
                  "input_profile_sha256": bundle.input_profile_sha256,
                  "files": {p.name: sha(p) for p in sorted(bundle.root.iterdir())}}
        result["frozen"] = frozen
        write_new(slot / "frozen.json", frozen)
        stage = "holdouts"

        def record(row):
            write_new(slot / "holdouts" / f"{len(rows) + 1:03d}.json", row)
            rows.append(row)

        audit_holdouts(bundle, contract(), slot / "holdout-workspaces", timeout=limits["holdout_seconds"],
                       continuation_guard=continuation, record=record)
        continuation()
        result.update(status="completed", stage="finished")
        code = 0
    except Exception as exc:  # noqa: BLE001 - never publish generated response or exception prose
        result.update(status="failed", stage=stage, error_class=type(exc).__name__)
        code = 1
    result.update(guard=guard.snapshot() if guard is not None else None,
                  elapsed_seconds=max(0, time.monotonic() - started))
    write_new(slot / "worker-finished.json", result)
    print(canonical({"status": result["status"], "stage": result["stage"],
                     "frozen": result["frozen"] is not None,
                     "holdouts_executed": sum(row["snapshot_started"] for row in rows)}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
