"""Pure, static plans for running a verified candidate source bundle.

Plans describe a runner invocation. They never stat the runner, read an environment from the
process, invoke a shell, or claim that dependencies and runtime state are reproducible.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _benchmark_files as _files
from .candidate_bundle import (
    MAX_CANDIDATE_BUNDLE_BYTES,
    CandidateBundleError,
    CandidateSourceBundle,
    parse_candidate_source_bundle,
    validate_candidate_source_bundle,
)

WORKSPACE_PLAN_PROTOCOL = "lunar-candidate-workspace-plan-v1"
WORKSPACE_PLAN_SCHEMA_VERSION = "1"
MAX_WORKSPACE_PLAN_BYTES = MAX_CANDIDATE_BUNDLE_BYTES
MAX_COMMAND_ITEMS = 32
MAX_COMMAND_ITEM_BYTES = 4096
MAX_ENVIRONMENT_ITEMS = 128
MAX_ENVIRONMENT_KEY_BYTES = 256
MAX_ENVIRONMENT_VALUE_BYTES = 4096
MAX_TIMEOUT_SECONDS = 86_400.0
MAX_OUTPUT_BYTES = 64 * 1024 * 1024


class CandidateWorkspaceError(ValueError):
    def __init__(self, suffix: str) -> None:
        self.code = suffix if suffix.startswith("candidate_workspace_") else "candidate_workspace_" + suffix
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise CandidateWorkspaceError(code)


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail("invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        content = encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("invalid")
    if len(content) > MAX_WORKSPACE_PLAN_BYTES:
        _fail("too_large")
    return content


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or "\x00" in value:
        _fail("invalid")
    try:
        if len(value.encode("utf-8")) > limit:
            _fail("invalid")
    except UnicodeEncodeError:
        _fail("invalid")
    return value


def _command(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_COMMAND_ITEMS:
        _fail("invalid")
    result = tuple(_text(item, MAX_COMMAND_ITEM_BYTES) for item in value)
    first = result[0]
    try:
        path = Path(first)
        if not path.is_absolute() or path.as_posix() != first or any(part in {"", ".", ".."} for part in path.parts):
            _fail("runner_unsafe")
    except (TypeError, ValueError):
        _fail("runner_unsafe")
    return result


def _environment(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        _fail("invalid")
    if len(items) > MAX_ENVIRONMENT_ITEMS:
        _fail("invalid")
    result: list[tuple[str, str]] = []
    for pair in items:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            _fail("invalid")
        key = _text(pair[0], MAX_ENVIRONMENT_KEY_BYTES)
        value_text = _text(pair[1], MAX_ENVIRONMENT_VALUE_BYTES)
        if not key or "=" in key or "/" in key or "\\" in key:
            _fail("invalid")
        result.append((key, value_text))
    if len({key for key, _ in result}) != len(result):
        _fail("invalid")
    return tuple(sorted(result))


def _validated_bundle(bundle: CandidateSourceBundle) -> CandidateSourceBundle:
    try:
        return validate_candidate_source_bundle(bundle)
    except CandidateBundleError:
        _fail("invalid")


def candidate_file_table_sha256(
    bundle: CandidateSourceBundle | Mapping[str, object] | str | os.PathLike[str],
) -> str:
    try:
        parsed = (
            _validated_bundle(bundle) if isinstance(bundle, CandidateSourceBundle)
            else parse_candidate_source_bundle(bundle)
        )
        return hashlib.sha256(_canonical([item.to_dict() for item in parsed.files])).hexdigest()
    except CandidateBundleError:
        _fail("invalid")


def _strict_object(value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("invalid")
    return value


@dataclass(frozen=True)
class CandidateWorkspacePlan:
    bundle: CandidateSourceBundle
    command: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 300.0
    max_output_bytes: int = 1 * 1024 * 1024
    workspace_cwd: str = "."
    schema_version: str = WORKSPACE_PLAN_SCHEMA_VERSION
    protocol: str = WORKSPACE_PLAN_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_PLAN_SCHEMA_VERSION or self.protocol != WORKSPACE_PLAN_PROTOCOL or self.workspace_cwd != ".":
            _fail("invalid")
        if not isinstance(self.bundle, CandidateSourceBundle):
            _fail("invalid")
        bundle = _validated_bundle(self.bundle)
        command = _command(self.command)
        environment = _environment(self.environment)
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            _fail("invalid")
        try:
            timeout = float(self.timeout_seconds)
        except (OverflowError, ValueError):
            _fail("invalid")
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
            _fail("invalid")
        if isinstance(self.max_output_bytes, bool) or not isinstance(self.max_output_bytes, int) or not 0 < self.max_output_bytes <= MAX_OUTPUT_BYTES:
            _fail("invalid")
        object.__setattr__(self, "bundle", bundle)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "timeout_seconds", timeout)
        _canonical(_plan_dict(self))

    @property
    def contract_sha256(self) -> str:
        return _validated_bundle(self.bundle).contract_sha256

    @property
    def bundle_sha256(self) -> str:
        return _validated_bundle(self.bundle).digest()

    @property
    def entrypoint(self) -> str:
        return _validated_bundle(self.bundle).entrypoint

    @property
    def file_count(self) -> int:
        return len(_validated_bundle(self.bundle).files)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in _validated_bundle(self.bundle).files)

    @property
    def file_table_sha256(self) -> str:
        return candidate_file_table_sha256(self.bundle)

    def to_dict(self) -> dict[str, object]:
        return _plan_dict(validate_candidate_workspace_plan(self))

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> CandidateWorkspacePlan:
        item = _strict_object(value, {"schema_version", "protocol", "bundle", "command", "environment", "timeout_seconds", "max_output_bytes", "workspace_cwd"})
        if not isinstance(item["command"], list) or not isinstance(item["environment"], dict):
            _fail("invalid")
        try:
            return cls(
                CandidateSourceBundle.from_dict(item["bundle"]), item["command"],
                item["environment"], item["timeout_seconds"], item["max_output_bytes"],
                item["workspace_cwd"], item["schema_version"], item["protocol"],
            )
        except CandidateBundleError:
            _fail("invalid")


def _plan_dict(plan: CandidateWorkspacePlan) -> dict[str, object]:
    return {
        "schema_version": plan.schema_version, "protocol": plan.protocol,
        "bundle": plan.bundle.to_dict(), "command": list(plan.command),
        "environment": {key: value for key, value in plan.environment},
        "timeout_seconds": plan.timeout_seconds, "max_output_bytes": plan.max_output_bytes,
        "workspace_cwd": plan.workspace_cwd,
    }


def parse_candidate_workspace_plan(source: str | os.PathLike[str] | Mapping[str, object]) -> CandidateWorkspacePlan:
    try:
        if isinstance(source, Mapping):
            return CandidateWorkspacePlan.from_dict(dict(source))
        content = _files.read_regular_file(_files.absolute_path(source), MAX_WORKSPACE_PLAN_BYTES)
        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in items:
                if key in result:
                    _fail("invalid")
                result[key] = item
            return result
        value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: _fail("invalid"))
        return CandidateWorkspacePlan.from_dict(value)
    except CandidateWorkspaceError:
        raise
    except _files.BenchmarkFileError as exc:
        _fail("too_large" if exc.reason == "too_large" else "invalid")
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
        _fail("invalid")


def validate_candidate_workspace_plan(plan: CandidateWorkspacePlan) -> CandidateWorkspacePlan:
    try:
        if not isinstance(plan, CandidateWorkspacePlan):
            _fail("invalid")
        # Replay raw tuple values before JSON conversion can erase duplicate environment keys.
        return CandidateWorkspacePlan(
            plan.bundle, plan.command, plan.environment, plan.timeout_seconds,
            plan.max_output_bytes, plan.workspace_cwd, plan.schema_version, plan.protocol,
        )
    except CandidateWorkspaceError:
        raise
    except (AttributeError, TypeError, ValueError, KeyError, RecursionError):
        _fail("invalid")


def build_candidate_workspace_plan(
    bundle: CandidateSourceBundle | Mapping[str, object] | str | os.PathLike[str],
    *,
    command: list[str] | tuple[str, ...],
    contract_sha256: str | None = None,
    timeout_seconds: float = 300.0,
    max_output_bytes: int = 1 * 1024 * 1024,
    environment: Mapping[str, str] | tuple[tuple[str, str], ...] | None = None,
    expected_bundle_sha256: str | None = None,
) -> CandidateWorkspacePlan:
    try:
        parsed = bundle if isinstance(bundle, CandidateSourceBundle) else parse_candidate_source_bundle(bundle)
        parsed = validate_candidate_source_bundle(parsed)
        if contract_sha256 is None:
            _fail("invalid")
        contract = _digest(contract_sha256)
        if contract != parsed.contract_sha256:
            _fail("contract_mismatch")
        identity = parsed.digest()
        if expected_bundle_sha256 is not None and _digest(expected_bundle_sha256) != identity:
            _fail("identity_mismatch")
        return CandidateWorkspacePlan(
            parsed, command, () if environment is None else environment,
            timeout_seconds, max_output_bytes,
        )
    except CandidateWorkspaceError:
        raise
    except CandidateBundleError:
        _fail("invalid")
    except (TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid")


__all__ = [
    "MAX_COMMAND_ITEMS",
    "MAX_COMMAND_ITEM_BYTES",
    "MAX_ENVIRONMENT_ITEMS",
    "MAX_ENVIRONMENT_KEY_BYTES",
    "MAX_ENVIRONMENT_VALUE_BYTES",
    "MAX_OUTPUT_BYTES",
    "MAX_TIMEOUT_SECONDS",
    "MAX_WORKSPACE_PLAN_BYTES",
    "WORKSPACE_PLAN_PROTOCOL",
    "WORKSPACE_PLAN_SCHEMA_VERSION",
    "CandidateWorkspaceError",
    "CandidateWorkspacePlan",
    "build_candidate_workspace_plan",
    "candidate_file_table_sha256",
    "parse_candidate_workspace_plan",
    "validate_candidate_workspace_plan",
]
