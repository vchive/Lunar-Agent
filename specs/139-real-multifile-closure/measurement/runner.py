"""Register, admit, supervise, and summarize the sole Feature 139 attempt.

The registration repository owns all authorization decisions. This module only
coordinates the admitted slot and preserves the compatibility surface used by
the retained-evidence analyzer.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - exercised by supervision
    _HERE = Path(__file__).resolve().parent
    _PACKAGE = "_lunar_measurement139"
    _spec = importlib.util.spec_from_file_location(
        _PACKAGE, _HERE / "__init__.py", submodule_search_locations=[str(_HERE)],
    )
    if _spec is None or _spec.loader is None:
        raise RuntimeError("measurement_package_unavailable")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_PACKAGE] = _module
    _spec.loader.exec_module(_module)
    __package__ = _PACKAGE

from .campaign import default_manifest
from .registration import (
    HERE,
    REPO,
    RegistrationStoreError,
    canonical_bytes,
    default_repository,
)
from .registration import (
    MANIFEST as _MANIFEST,
)
from .supervision import supervise

MANIFEST = _MANIFEST


_BUDGETS = default_manifest()["budgets"]
LIMITS = {
    "request_seconds": _BUDGETS["request_timeout_seconds"],
    "preparation_request_seconds": _BUDGETS["preparation_request_timeout_seconds"],
    "preparation_wall_seconds": _BUDGETS["preparation_wall_seconds"],
    "wall_seconds": _BUDGETS["wall_seconds"],
    "max_requests": _BUDGETS["max_requests"],
    "token_stop_threshold": _BUDGETS["observed_token_stop"],
    "candidate_seconds": _BUDGETS["request_timeout_seconds"],
    "candidate_generation_max_steps": _BUDGETS["candidate_steps"],
    "holdout_seconds": _BUDGETS["holdout_seconds"],
}


def canonical(value: object) -> str:
    """Return the canonical JSON representation used by public CLI output."""
    return canonical_bytes(value).decode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc() -> str:
    return datetime.now(UTC).isoformat()


def write_new(path: Path, value: object) -> None:
    """Write one retained artifact without overwriting an existing file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        raw = canonical_bytes(value)
        written = 0
        while written < len(raw):
            written += os.write(descriptor, raw[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def register() -> dict[str, object]:
    """Create the canonical manifest. This never makes a provider request."""
    return default_repository().register()


def verify(*, committed: bool = False, require_unused_root: bool = False) -> dict[str, Any]:
    """Reload the manifest and validate the current checkout against it."""
    repository = default_repository()
    verified = repository.verify_launch() if require_unused_root else repository.verify(committed=committed)
    return verified.manifest


def _admission_matches(marker: dict[str, object], manifest: dict[str, Any], manifest_sha256: str) -> None:
    expected = {
        "schema_version": "1",
        "registration_id": manifest["registration_id"],
        "campaign_id": manifest["campaign_id"],
        "attempt_id": manifest["attempt_id"],
        "manifest_sha256": manifest_sha256,
    }
    if any(marker.get(key) != value for key, value in expected.items()):
        raise RegistrationStoreError("admission_binding_changed")


def run(manifest: dict[str, Any] | None = None, runner=supervise) -> dict[str, object]:
    """Atomically consume and supervise the only slot after a fresh preflight."""
    repository = default_repository()
    preflight = repository.verify_launch()
    if manifest is not None and manifest != preflight.manifest:
        raise RegistrationStoreError("caller_manifest_changed")
    marker = repository.admit_one_slot()
    _admission_matches(marker, preflight.manifest, preflight.manifest_sha256)

    root = REPO / preflight.manifest["campaign_root"]
    slot = root / preflight.manifest["attempt_id"]
    identity = {
        "registration_id": preflight.manifest["registration_id"],
        "campaign_id": preflight.manifest["campaign_id"],
        "attempt_id": preflight.manifest["attempt_id"],
        "registration_commit": marker["registration_commit"],
        "manifest_sha256": preflight.manifest_sha256,
    }
    write_new(root / "started.json", {**identity, "started_utc": utc()})
    write_new(slot / "started.json", {**identity, "index": 1, "started_utc": utc()})

    started = time.monotonic()
    try:
        outcome = runner(
            [sys.executable, str(HERE / "worker.py")], slot, LIMITS["wall_seconds"],
        )
    except BaseException as exc:  # noqa: BLE001 - an admitted slot needs a terminal receipt
        outcome = {
            "process_status": "supervisor_failed",
            "exit_code": None,
            "elapsed_seconds": max(0.0, time.monotonic() - started),
            "cleanup_verified": False,
            "remaining_observed_pids": [],
            "error_type": type(exc).__name__,
        }
    write_new(slot / "finished.json", outcome)
    final = {
        **identity,
        "finished_utc": utc(),
        "planned_attempts": 1,
        "status": "finished" if outcome.get("cleanup_verified") else "cleanup_unverified",
    }
    write_new(root / "finished.json", final)
    return final


def summarize(manifest: dict[str, Any] | None = None) -> dict[str, object]:
    """Produce the public result after the admitted attempt ends."""
    try:
        from .analysis import summarize as analyze
    except ImportError:  # pragma: no cover - direct script entry point
        from analysis import summarize as analyze

    verified = default_repository().verify(committed=True)
    if manifest is not None and manifest != verified.manifest:
        raise RegistrationStoreError("caller_manifest_changed")
    return analyze(verified.manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "verify", "run", "summarize"))
    args = parser.parse_args()
    if args.action == "register":
        result = register()
    elif args.action == "verify":
        verified = default_repository().verify(committed=False)
        result = {"status": "verified", "manifest_sha256": verified.manifest_sha256}
    elif args.action == "run":
        result = run()
    else:
        result = summarize()
    print(canonical(result), end="")


if __name__ == "__main__":
    main()
