"""Deterministic, value-free structural profiles for staged algorithm inputs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path

from .algorithm import AlgorithmProblemContract
from .evolution import CandidateInputArtifact

MAX_PROFILE_ROWS = 1_000_000
MAX_PROFILE_FIELDS = 256
MAX_PROFILE_DEPTH = 16
MAX_PROFILE_FIELD_BYTES = 512
MAX_PROFILE_BYTES = 512 * 1024
SUPPORTED_PROFILE_FORMATS = frozenset({"csv", "json", "jsonl", "text"})
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


class DataProfileError(RuntimeError):
    """Input bytes cannot be admitted into a deterministic private profile."""


def build_private_input_profile(
    workspace: Path,
    contract: AlgorithmProblemContract,
    inputs: tuple[CandidateInputArtifact, ...],
) -> dict[str, object]:
    """Return structure-only metadata after verifying exact staged input bytes."""
    if not isinstance(contract, AlgorithmProblemContract):
        raise TypeError("contract must be an AlgorithmProblemContract")
    raw_root = Path(workspace).expanduser()
    if raw_root.is_symlink():
        raise DataProfileError("data profile workspace must not be a symlink")
    root = raw_root.resolve(strict=False)
    specs = {f"data/raw/{item.path}": item for item in contract.inputs}
    if any(not isinstance(item, CandidateInputArtifact) for item in inputs):
        raise TypeError("inputs must contain CandidateInputArtifact records")
    descriptors = {item.path: item for item in inputs}
    if len(descriptors) != len(inputs):
        raise DataProfileError("data profile descriptors contain duplicate paths")
    if set(specs) != set(descriptors):
        raise DataProfileError("data profile descriptors do not match declared inputs")
    files: list[dict[str, object]] = []
    for relative in sorted(specs):
        spec = specs[relative]
        descriptor = descriptors[relative]
        content = _verified_bytes(root, descriptor)
        format_name = spec.format.strip().lower()
        if format_name not in SUPPORTED_PROFILE_FORMATS:
            raise DataProfileError(f"unsupported input profile format: {format_name}")
        base: dict[str, object] = {
            "path": relative,
            "format": format_name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        if format_name == "text":
            text = _utf8(content)
            base.update({"line_count": len(text.splitlines()), "fields": []})
        else:
            records = _records(format_name, content)
            base.update(
                {
                    "row_count": len(records),
                    "fields": _field_profiles(records),
                }
            )
        files.append(base)
    profile: dict[str, object] = {"schema_version": "1", "files": files}
    canonical_profile_json(profile)
    return profile


def canonical_profile_json(profile: dict[str, object]) -> str:
    """Return the one bounded byte representation used for storage and identity."""
    try:
        encoded = json.dumps(
            profile,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DataProfileError("private input profile is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise DataProfileError("private input profile exceeds the bounded size")
    if _SECRET.search(encoded):
        raise DataProfileError("private input profile contains credential-like content")
    return encoded


def profile_sha256(profile: dict[str, object]) -> str:
    encoded = canonical_profile_json(profile)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _verified_bytes(root: Path, descriptor: CandidateInputArtifact) -> bytes:
    raw = root / descriptor.path
    current = raw
    while current != root:
        if current.is_symlink():
            raise DataProfileError("data profile input path contains a symlink")
        try:
            current.relative_to(root)
        except ValueError as exc:
            raise DataProfileError("data profile input escapes the workspace") from exc
        current = current.parent
    resolved = raw.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DataProfileError("data profile input escapes the workspace") from exc
    if raw.is_symlink() or not resolved.is_file():
        raise DataProfileError("data profile input is missing or unsafe")
    content = resolved.read_bytes()
    if len(content) != descriptor.size or hashlib.sha256(content).hexdigest() != descriptor.sha256:
        raise DataProfileError("data profile input digest does not match")
    return content


def _utf8(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataProfileError("data profile input is not valid UTF-8") from exc


def _records(format_name: str, content: bytes) -> list[dict[str, object]]:
    text = _utf8(content)
    if format_name == "csv":
        try:
            rows = csv.reader(io.StringIO(text), strict=True)
            headers = next(rows, None)
            if not headers or any(not header for header in headers):
                raise DataProfileError("CSV input requires non-empty headers")
            if len(headers) > MAX_PROFILE_FIELDS or len(set(headers)) != len(headers):
                raise DataProfileError("CSV input has duplicate or excessive headers")
            _validate_field_names(headers)
            records = []
            for row in rows:
                if len(row) != len(headers):
                    raise DataProfileError("CSV input row width does not match its header")
                records.append(dict(zip(headers, row, strict=True)))
        except csv.Error as exc:
            raise DataProfileError("CSV input is malformed") from exc
    elif format_name == "json":
        try:
            payload = _strict_json_loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise DataProfileError("JSON input is malformed") from exc
        _bounded_depth(payload)
        if isinstance(payload, dict):
            records = [payload]
        elif isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            records = list(payload)
        else:
            raise DataProfileError("JSON input must contain an object or array of objects")
    else:
        records = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = _strict_json_loads(line)
            except (json.JSONDecodeError, ValueError) as exc:
                raise DataProfileError(f"JSONL input line {line_number} is malformed") from exc
            _bounded_depth(item)
            if not isinstance(item, dict):
                raise DataProfileError("JSONL input records must be objects")
            records.append(item)
    if len(records) > MAX_PROFILE_ROWS:
        raise DataProfileError("input exceeds the private profile row limit")
    if any(not isinstance(key, str) for record in records for key in record):
        raise DataProfileError("input field names must be strings")
    fields = {key for record in records for key in record}
    if len(fields) > MAX_PROFILE_FIELDS:
        raise DataProfileError("input exceeds the private profile field limit")
    _validate_field_names(fields)
    return records


def _validate_field_names(names: object) -> None:
    for name in names:  # type: ignore[union-attr]
        if (
            not isinstance(name, str)
            or not name
            or "\x00" in name
            or len(name.encode("utf-8")) > MAX_PROFILE_FIELD_BYTES
        ):
            raise DataProfileError("input contains an invalid or excessive field name")
        if _SECRET.search(name):
            raise DataProfileError("input field name contains credential-like content")


def _strict_json_loads(text: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _field_profiles(records: list[dict[str, object]]) -> list[dict[str, object]]:
    names = list(dict.fromkeys(key for record in records for key in record))
    profiles: list[dict[str, object]] = []
    for name in names:
        values = [record.get(name) for record in records]
        non_null = [value for value in values if value is not None and value != ""]
        kinds = {_kind(value) for value in non_null}
        unique = {_canonical_value(value) for value in non_null}
        profiles.append(
            {
                "name": name,
                "type": next(iter(kinds)) if len(kinds) == 1 else ("null" if not kinds else "mixed"),
                "null_count": len(values) - len(non_null),
                "unique_count": len(unique),
            }
        )
    return profiles


def _kind(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "mixed"


def _canonical_value(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _bounded_depth(value: object, depth: int = 1) -> None:
    if depth > MAX_PROFILE_DEPTH:
        raise DataProfileError("input exceeds the private profile nesting limit")
    if isinstance(value, dict):
        for item in value.values():
            _bounded_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _bounded_depth(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DataProfileError("input contains a non-finite number")


__all__ = [
    "DataProfileError",
    "build_private_input_profile",
    "canonical_profile_json",
    "profile_sha256",
]
