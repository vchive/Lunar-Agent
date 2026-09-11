"""Exercise the public host scope locally, without a model or evaluator.

Requires macOS and a fresh --output-directory under an existing physical directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from famou.host_awake import MacOSIdleSleepAssertion
from famou.host_session import host_execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    destination = parser.parse_args().output_directory
    destination.mkdir()
    results = []
    for exceptional in (False, True):
        guard = MacOSIdleSleepAssertion()
        path = destination / ("raised.jsonl" if exceptional else "returned.jsonl")
        body_exception = RuntimeError("fixed local validation exception")
        try:
            with host_execution(path, guard=guard):
                evidence = guard.verify()
                if exceptional:
                    raise body_exception
        except RuntimeError as error:
            if not exceptional or error is not body_exception:
                raise
        raw = guard._api.io.IOPMAssertionCopyProperties(evidence["assertion_id"])
        if raw:
            guard._api.cf.CFRelease(raw)
            raise ValueError("scope_smoke_release_failed")
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert [record["event"] for record in records] == ["starting", "active", "closed"]
        assert records[-1]["work_outcome"] == ("raised" if exceptional else "returned")
        assert records[-1]["verification_outcome"] == "verified"
        assert records[-1]["release_outcome"] == "returned"
        results.append({
            "journal": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "work_outcome": records[-1]["work_outcome"], "scope_cleanup_completed": True,
            "queried_after_release_absent": True,
        })
    root = Path(__file__).resolve().parents[3]
    report = {
        "schema_version": "1", "kind": "feature083_native_scope_smoke",
        "completed_utc": datetime.now(UTC).isoformat(), "owner_pid": os.getpid(),
        "source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "src/famou/host_awake.py", "src/famou/host_session.py", "src/famou/cli.py",
                "specs/083-host-execution-guard/validation/native-scope-smoke.py",
            )
        },
        "scopes": results, "passed": True, "model_calls": 0, "network_calls": 0,
        "system_sleep_requested": False, "permanent_settings_changed": False,
        "limitations": "Local point-in-time assertion and public-scope cleanup evidence only.",
    }
    with (destination / "result.json").open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "scopes_verified": len(results)}))


if __name__ == "__main__":
    main()
