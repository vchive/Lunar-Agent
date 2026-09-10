"""Read-only Feature 076 audit through the pinned, explicitly rebound two-slot validator."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
MEASUREMENT = HERE.parent / "measurement"


def load_file(name, path):
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102
    return module


_adapter = load_file("postrun076_adapter", MEASUREMENT / "adapter.py")
verify_registration = _adapter.load_previous_postrun().verify_registration


def dependencies():
    adapter = load_file("postrun076_current_adapter", MEASUREMENT / "adapter.py")
    return adapter, adapter.load_legacy("postrun")


def audit_registered_campaign(manifest_path, campaign_path, *, require_complete=False):
    # The prior module owns only validation: no controller construction, recovery or dispatch.
    # Rebind its current dependency graph and analysis identity; never use its old campaign paths.
    prior = _adapter.load_previous_postrun(overrides={
        "MEASUREMENT": MEASUREMENT, "dependencies": dependencies,
        "verify_registration": verify_registration, "__file__": str(Path(__file__).resolve()),
    })
    result = prior.audit_registered_campaign(
        manifest_path, campaign_path, require_complete=require_complete,
    )
    result["kind"] = "feature076_postrun_audit"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    try:
        adapter, _legacy = dependencies()
        result = audit_registered_campaign(MEASUREMENT / "manifest.json", adapter.CAMPAIGN,
                                           require_complete=args.require_complete)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"passed": False, "error": "unavailable or inconsistent evidence", "model_calls": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
