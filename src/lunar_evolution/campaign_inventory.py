"""Provider-free inventory and audit of one retained acceptance campaign directory.

The inventory is intentionally a byte-level observation only.  It never imports or executes
campaign material, opens SQLite, invokes an evaluator, starts a subprocess, or mutates the
directory.  A caller can retain the returned canonical record outside the campaign tree and use
``audit_campaign_directory`` later to recompute it read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from typing import Any

from ._benchmark_files import absolute_path
from ._candidate_workspace_io import DirectoryChain

INVENTORY_PROTOCOL = "lunar-acceptance-campaign-inventory-v1"
INVENTORY_SCHEMA_VERSION = "1"
MAX_INVENTORY_FILES = 4096
MAX_INVENTORY_FILE_BYTES = 32 * 1024 * 1024
MAX_INVENTORY_TOTAL_BYTES = 256 * 1024 * 1024
MAX_INVENTORY_PATH_BYTES = 1024
MAX_INVENTORY_DEPTH = 64
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FIELDS = frozenset({
    "schema_version", "protocol", "campaign_root", "files", "file_count", "total_bytes",
    "inventory_sha256",
})
_FILE_FIELDS = frozenset({"path", "size", "sha256"})
_CHUNK_BYTES = 1024 * 1024


class CampaignInventoryError(ValueError):
    """A fixed public code for an unsafe, changing, or inconsistent inventory."""

    _CODES = frozenset({
        "invalid", "root_unsafe", "root_missing", "root_changed", "file_unsafe", "file_missing",
        "file_changed", "file_too_large", "total_too_large", "too_many_files", "schema_invalid",
        "digest_invalid", "digest_mismatch", "inventory_mismatch",
    })

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and code in self._CODES else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise CampaignInventoryError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("schema_invalid")


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _relative(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\x00" in path:
        _fail("schema_invalid")
    parts = path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        _fail("schema_invalid")
    try:
        encoded = path.encode("utf-8")
    except UnicodeError:
        _fail("schema_invalid")
    if len(encoded) > MAX_INVENTORY_PATH_BYTES:
        _fail("schema_invalid")
    return path


def _validate_inventory(value: object, *, require_digest: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _fail("schema_invalid")
    if value["schema_version"] != INVENTORY_SCHEMA_VERSION or value["protocol"] != INVENTORY_PROTOCOL:
        _fail("schema_invalid")
    root = value["campaign_root"]
    if not isinstance(root, str) or _ROOT.fullmatch(root) is None:
        _fail("schema_invalid")
    files = value["files"]
    if not isinstance(files, list) or len(files) > MAX_INVENTORY_FILES:
        _fail("schema_invalid")
    normalized: list[dict[str, Any]] = []
    previous = None
    total = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != _FILE_FIELDS:
            _fail("schema_invalid")
        path = _relative(item["path"])
        if previous is not None and path <= previous:
            _fail("schema_invalid")
        previous = path
        size = item["size"]
        if type(size) is not int or size < 0 or size > MAX_INVENTORY_FILE_BYTES:
            _fail("schema_invalid")
        total += size
        if total > MAX_INVENTORY_TOTAL_BYTES:
            _fail("total_too_large")
        normalized.append({"path": path, "size": size, "sha256": _digest(item["sha256"])})
    if type(value["file_count"]) is not int or value["file_count"] != len(normalized):
        _fail("schema_invalid")
    if type(value["total_bytes"]) is not int or value["total_bytes"] != total:
        _fail("schema_invalid")
    digest = value["inventory_sha256"]
    if require_digest:
        _digest(digest)
    payload = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "protocol": INVENTORY_PROTOCOL,
        "campaign_root": root,
        "files": normalized,
        "file_count": len(normalized),
        "total_bytes": total,
    }
    expected = hashlib.sha256(_canonical(payload)).hexdigest()
    if require_digest and digest != expected:
        _fail("digest_mismatch")
    result = {**payload, "inventory_sha256": expected}
    if require_digest and _canonical(value) != _canonical(result):
        _fail("schema_invalid")
    return result


def _read_file(parent: int, name: str) -> tuple[int, str]:
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        _fail("file_missing")
    except OSError:
        _fail("file_unsafe")
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INVENTORY_FILE_BYTES:
        _fail("file_too_large" if stat.S_ISREG(before.st_mode) else "file_unsafe")
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    except FileNotFoundError:
        _fail("file_missing")
    except OSError:
        _fail("file_unsafe")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            _fail("file_changed")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_INVENTORY_FILE_BYTES:
                _fail("file_too_large")
            digest.update(chunk)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if identity(after) != identity(before) or identity(named) != identity(before) or total != before.st_size:
            _fail("file_changed")
        return total, digest.hexdigest()
    except FileNotFoundError:
        _fail("file_changed")
    except OSError:
        _fail("file_changed")
    finally:
        os.close(descriptor)


def _directory_snapshot(parent: int) -> dict[str, tuple[int, tuple[int, ...]]]:
    try:
        with os.scandir(parent) as entries:
            snapshot = {}
            for entry in entries:
                name = entry.name
                if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
                    _fail("file_unsafe")
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                    _fail("file_unsafe")
                snapshot[name] = (stat.S_IFMT(info.st_mode), _identity(info))
            return snapshot
    except FileNotFoundError:
        _fail("root_changed")
    except OSError:
        _fail("file_unsafe")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _walk(parent: int, prefix: str, records: list[dict[str, Any]], total: list[int], *, depth: int = 0) -> None:
    if depth > MAX_INVENTORY_DEPTH:
        _fail("too_many_files")
    initial = _directory_snapshot(parent)
    for name in sorted(initial):
        relative = f"{prefix}/{name}" if prefix else name
        _relative(relative)
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            _fail("root_changed")
        except OSError:
            _fail("file_unsafe")
        if stat.S_ISDIR(info.st_mode):
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                opened = os.fstat(child)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    _fail("root_changed")
                try:
                    _walk(child, relative, records, total, depth=depth + 1)
                finally:
                    os.close(child)
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    _fail("root_changed")
            except FileNotFoundError:
                _fail("root_changed")
            except OSError:
                _fail("file_unsafe")
            continue
        if not stat.S_ISREG(info.st_mode):
            _fail("file_unsafe")
        size, digest = _read_file(parent, name)
        records.append({"path": relative, "size": size, "sha256": digest})
        total[0] += size
        if total[0] > MAX_INVENTORY_TOTAL_BYTES:
            _fail("total_too_large")
        if len(records) > MAX_INVENTORY_FILES:
            _fail("too_many_files")
    if _directory_snapshot(parent) != initial:
        _fail("root_changed")


def inventory_campaign_directory(root: str | os.PathLike[str]) -> dict[str, Any]:
    """Return a canonical, bounded inventory of every regular file under ``root``."""
    try:
        path = absolute_path(root)
        if not path.name or _ROOT.fullmatch(path.name) is None:
            _fail("root_unsafe")
        chain = DirectoryChain(path, "root_unsafe")
    except CampaignInventoryError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError):
        _fail("root_missing")
    try:
        records: list[dict[str, Any]] = []
        total = [0]
        _walk(chain.fd, "", records, total)
        chain.check()
        payload = {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "protocol": INVENTORY_PROTOCOL,
            "campaign_root": path.name,
            "files": sorted(records, key=lambda item: item["path"]),
            "file_count": len(records),
            "total_bytes": total[0],
        }
        return {**payload, "inventory_sha256": hashlib.sha256(_canonical(payload)).hexdigest()}
    except CampaignInventoryError:
        raise
    except (OSError, RuntimeError, ValueError):
        _fail("root_changed")
    finally:
        chain.close()


def audit_campaign_directory(root: str | os.PathLike[str], expected: dict[str, Any]) -> dict[str, Any]:
    """Recompute and compare a retained inventory; never writes or executes campaign files."""
    parsed = _validate_inventory(expected)
    observed = inventory_campaign_directory(root)
    if observed != parsed:
        _fail("inventory_mismatch")
    return {
        "status": "verified",
        "protocol": INVENTORY_PROTOCOL,
        "campaign_root": parsed["campaign_root"],
        "inventory_sha256": parsed["inventory_sha256"],
        "file_count": parsed["file_count"],
        "total_bytes": parsed["total_bytes"],
    }


__all__ = [
    "INVENTORY_PROTOCOL",
    "INVENTORY_SCHEMA_VERSION",
    "MAX_INVENTORY_DEPTH",
    "MAX_INVENTORY_FILES",
    "MAX_INVENTORY_FILE_BYTES",
    "MAX_INVENTORY_TOTAL_BYTES",
    "CampaignInventoryError",
    "audit_campaign_directory",
    "inventory_campaign_directory",
]
