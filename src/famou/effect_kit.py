"""Build a deterministic, public-only EffectTrial kit from local Famou case bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .effect_adapters import EffectAdapterError, famou_case_content_digest
from .effect_trial import TrialSuite

MAX_CASES = 2
MAX_PUBLIC_FILES = 128
MAX_PUBLIC_FILE_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EXCLUDED_NAMES = {".DS_Store", "__pycache__"}


class EffectKitError(ValueError):
    """A local case tree cannot produce a safe content-addressed effect kit."""


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _object_digest(payload: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: object) -> bytes:
    content = _canonical_bytes(payload)
    if len(content) > MAX_JSON_BYTES:
        raise EffectKitError(f"{path.name} exceeds its bounded size")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return content


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise EffectKitError(f"{label} must be a safe identifier")
    return value


def _case_root(value: str | Path, key: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise EffectKitError(f"case root must be absolute: {key}")
    if raw.is_symlink() or not raw.is_dir():
        raise EffectKitError(f"case root is missing, linked, or not a directory: {key}")
    return raw.resolve()


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise EffectKitError(f"{label} must be a regular non-linked file")
    return path


def _inspect_case(key: str, source: Path) -> dict[str, object]:
    try:
        content_digest = famou_case_content_digest(source)
    except EffectAdapterError as exc:
        raise EffectKitError(str(exc)) from exc
    instruction = _regular_file(source / "instruction.md", f"case {key} instruction")
    data_root = source / "data"
    if data_root.is_symlink() or not data_root.is_dir():
        raise EffectKitError(f"case {key} data directory is missing or linked")
    entries = sorted(
        (
            path
            for path in data_root.iterdir()
            if path.name not in _EXCLUDED_NAMES and not path.name.endswith(".pyc")
        ),
        key=lambda value: value.name.encode("utf-8"),
    )
    if not entries or any(not path.is_file() or path.is_symlink() for path in entries):
        raise EffectKitError(f"case {key} data must contain direct regular files")
    public_sources = [("instruction.md", instruction)] + [
        (f"data/{path.name}", _regular_file(path, f"case {key} data file"))
        for path in entries
    ]
    if len(public_sources) > MAX_PUBLIC_FILES:
        raise EffectKitError(f"case {key} has too many public files")
    public_files: list[dict[str, object]] = []
    for relative, path in public_sources:
        size = path.stat().st_size
        if size > MAX_PUBLIC_FILE_BYTES:
            raise EffectKitError(f"case {key} public file exceeds its bounded size: {relative}")
        public_files.append(
            {"path": relative, "size": size, "sha256": _file_digest(path)}
        )
    extractor = _regular_file(
        source / "tests" / "extractor_agent.py", f"case {key} extractor"
    )
    evaluator = _regular_file(source / "tests" / "evaluator.py", f"case {key} evaluator")
    harness = {
        "extractor_sha256": _file_digest(extractor),
        "evaluator_sha256": _file_digest(evaluator),
    }
    return {
        "key": key,
        "source": source,
        "revision_id": "local-" + content_digest.removeprefix("sha256:"),
        "digest": content_digest,
        "entrypoint": "instruction.md",
        "public_files": public_files,
        "public_sources": public_sources,
        "harness": harness,
    }


def _copy_public_case(case: Mapping[str, object], output: Path) -> None:
    projection = output / "cases" / str(case["key"])
    projection.mkdir(parents=True)
    sources = case["public_sources"]
    if not isinstance(sources, list):
        raise EffectKitError("internal public source ledger is invalid")
    for relative, raw_source in sources:
        source = Path(raw_source)
        target = projection / str(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    expected = {
        str(item["path"]): (int(item["size"]), str(item["sha256"]))
        for item in case["public_files"]
    }
    actual: dict[str, tuple[int, str]] = {}
    for path in projection.rglob("*"):
        if path.is_symlink():
            raise EffectKitError("projected public case unexpectedly contains a link")
        if path.is_file():
            actual[path.relative_to(projection).as_posix()] = (
                path.stat().st_size,
                _file_digest(path),
            )
    if actual != expected:
        raise EffectKitError(f"public projection verification failed: {case['key']}")


def build_effect_kit(
    output_directory: str | Path,
    case_sources: Mapping[str, str | Path],
    *,
    benchmark_name: str = "famou-bench",
    evaluation_profile_name: str = "famou-agentco-default",
    evaluation_profile_revision: int = 1,
    owner_attested_content_equivalence: bool = False,
) -> dict[str, object]:
    """Build one new content-addressed kit without persisting private source paths."""
    if not isinstance(case_sources, Mapping) or not 1 <= len(case_sources) <= MAX_CASES:
        raise EffectKitError("effect kit requires exactly one or two case mappings")
    benchmark_name = _safe_id(benchmark_name, "benchmark name")
    evaluation_profile_name = _safe_id(
        evaluation_profile_name, "evaluation profile name"
    )
    if (
        isinstance(evaluation_profile_revision, bool)
        or not isinstance(evaluation_profile_revision, int)
        or not 1 <= evaluation_profile_revision <= 1_000_000
    ):
        raise EffectKitError("evaluation profile revision must be between 1 and 1000000")
    if not isinstance(owner_attested_content_equivalence, bool):
        raise EffectKitError("owner content-equivalence attestation must be boolean")

    normalized_sources: list[tuple[str, Path]] = []
    for raw_key, raw_source in case_sources.items():
        key = _safe_id(raw_key, "case key")
        normalized_sources.append((key, _case_root(raw_source, key)))
    normalized_sources.sort(key=lambda value: value[0].encode("utf-8"))
    if len({key for key, _ in normalized_sources}) != len(normalized_sources):
        raise EffectKitError("case keys must be unique")

    output = Path(output_directory).expanduser().resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise EffectKitError("effect kit output already exists")
    inspected = [_inspect_case(key, source) for key, source in normalized_sources]
    profile_payload = {
        "schema_revision": "lunar-local-evaluation-profile-v1",
        "name": evaluation_profile_name,
        "revision": evaluation_profile_revision,
        "case_harnesses": [
            {"key": case["key"], "harness": case["harness"]} for case in inspected
        ],
    }
    evaluation_profile = {
        "name": evaluation_profile_name,
        "revision": evaluation_profile_revision,
        "digest": _object_digest(profile_payload),
    }
    publication_payload = {
        "schema_revision": "lunar-local-publication-v1",
        "benchmark_name": benchmark_name,
        "evaluation_profile": evaluation_profile,
        "cases": [
            {
                "key": case["key"],
                "digest": case["digest"],
                "harness": case["harness"],
                "public_files": case["public_files"],
            }
            for case in inspected
        ],
    }
    publication_digest = _object_digest(publication_payload)
    benchmark = {
        "name": benchmark_name,
        "release_version": "content-" + publication_digest.removeprefix("sha256:")[:16],
        "publication_digest": publication_digest,
    }
    suite_payload = {
        "schema_version": "1",
        "benchmark": benchmark,
        "evaluation_profile": evaluation_profile,
        "cases": [
            {
                "key": case["key"],
                "revision_id": case["revision_id"],
                "digest": case["digest"],
                "entrypoint": case["entrypoint"],
                "public_files": case["public_files"],
                "harness": case["harness"],
            }
            for case in inspected
        ],
    }
    TrialSuite.from_dict(suite_payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise EffectKitError("effect kit output parent is unsafe")

    created_identity: tuple[int, int] | None = None
    try:
        output.mkdir()
        created_info = os.lstat(output)
        created_identity = (created_info.st_dev, created_info.st_ino)
        for case in inspected:
            _copy_public_case(case, output)
            try:
                current_digest = famou_case_content_digest(case["source"])
            except EffectAdapterError as exc:
                raise EffectKitError(str(exc)) from exc
            if current_digest != case["digest"]:
                raise EffectKitError(f"private case changed during kit build: {case['key']}")
        suite_bytes = _atomic_json(output / "suite.json", suite_payload)
        identity_basis = (
            "owner_attested_content_equivalent"
            if owner_attested_content_equivalence
            else "local_content"
        )
        manifest: dict[str, object] = {
            "schema_version": "1",
            "identity_basis": identity_basis,
            "owner_attested_content_equivalence": owner_attested_content_equivalence,
            "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
            "benchmark": benchmark,
            "evaluation_profile": evaluation_profile,
            "cases": [
                {
                    "key": case["key"],
                    "revision_id": case["revision_id"],
                    "digest": case["digest"],
                    "public_projection": f"cases/{case['key']}",
                    "harness": case["harness"],
                }
                for case in inspected
            ],
        }
        _atomic_json(output / "kit.json", manifest)
        return manifest
    except Exception:
        if created_identity is not None:
            try:
                current_info = os.lstat(output)
            except FileNotFoundError:
                pass
            else:
                current_identity = (current_info.st_dev, current_info.st_ino)
                if (
                    stat.S_ISDIR(current_info.st_mode)
                    and current_identity == created_identity
                ):
                    shutil.rmtree(output)
        raise


__all__ = ["EffectKitError", "build_effect_kit"]
