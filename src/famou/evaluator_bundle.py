"""Compile, preflight, freeze, and reload a local algorithm evaluator bundle.

The generated evaluator is explicit executable authority.  This module reduces that authority with
a strict envelope, a conservative source check, synthetic probes, minimal subprocess environment,
and content-addressed recovery; it does not claim to be an operating-system sandbox.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .algorithm import AlgorithmProblemContract, EvaluationReport
from .data_profile import (
    DataProfileError,
    build_private_input_profile,
    canonical_profile_json,
    profile_sha256,
)
from .evaluator import acceptance_evaluator
from .evolution import CandidateExecution, CandidateInputArtifact, EvolutionError
from .runtime import Runtime, RuntimeResult

MAX_BUNDLE_RESPONSE_BYTES = 512 * 1024
MAX_OBJECTIVE_BYTES = 32 * 1024
MAX_EVALUATOR_BYTES = 128 * 1024
MAX_PROBES = 64
MAX_PROBE_FILES = 32
MAX_PROBE_FILE_BYTES = 64 * 1024
MAX_PROBE_BYTES = 512 * 1024
MAX_EVALUATOR_OUTPUT_BYTES = 64 * 1024
MAX_IDENTIFIER_BYTES = 128
BUNDLE_PROTOCOL = "frozen-evaluator-bundle-v2"
BUNDLE_FILES = frozenset(
    {
        "audit.json",
        "objective.md",
        "evaluator.py",
        "probes.json",
        "input-profile.json",
        "manifest.json",
    }
)
_ALLOWED_IMPORTS = frozenset(
    {
        "bisect",
        "collections",
        "csv",
        "datetime",
        "decimal",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "json",
        "math",
        "pathlib",
        "statistics",
        "sys",
    }
)
_DANGEROUS_CALLS = frozenset(
    {
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)
_DANGEROUS_ATTRIBUTES = frozenset(
    {
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "truncate",
        "unlink",
        "write",
        "write_bytes",
        "write_text",
        "writelines",
    }
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


class EvaluatorBundleError(EvolutionError):
    """A bounded evaluator compilation, preflight, or integrity failure."""


class BundleRuntime(Protocol):
    name: str

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        ...


@dataclass(frozen=True)
class ProbeFile:
    path: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "content": self.content}


@dataclass(frozen=True)
class EvaluatorProbe:
    name: str
    constraint_id: str | None
    expected_validity: int
    files: tuple[ProbeFile, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "constraint_id": self.constraint_id,
            "expected_validity": self.expected_validity,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True)
class ScoreOrder:
    better: str
    worse: str

    def to_dict(self) -> dict[str, str]:
        return {"better": self.better, "worse": self.worse}


@dataclass(frozen=True)
class EvaluatorBundleEnvelope:
    objective: str
    evaluator_source: str
    constraint_coverage: tuple[str, ...]
    probes: tuple[EvaluatorProbe, ...]
    score_order: tuple[ScoreOrder, ...]

    def probe_suite(self) -> ProbeSuite:
        return ProbeSuite(self.constraint_coverage, self.probes, self.score_order)


@dataclass(frozen=True)
class ProbeSuite:
    constraint_coverage: tuple[str, ...]
    probes: tuple[EvaluatorProbe, ...]
    score_order: tuple[ScoreOrder, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "constraint_coverage": list(self.constraint_coverage),
            "probes": [item.to_dict() for item in self.probes],
            "score_order": [item.to_dict() for item in self.score_order],
        }


@dataclass(frozen=True)
class FrozenEvaluatorBundle:
    root: Path
    fingerprint: str
    contract_sha256: str
    input_profile_sha256: str
    timeout_seconds: float = 900.0

    def __call__(
        self, candidate_path: Path, contract: AlgorithmProblemContract
    ) -> EvaluationReport:
        if contract.digest() != self.contract_sha256:
            raise EvaluatorBundleError("frozen evaluator contract digest does not match")
        verified = load_evaluator_bundle(self.root, contract, timeout=self.timeout_seconds)
        if verified.fingerprint != self.fingerprint:
            raise EvaluatorBundleError("frozen evaluator bundle fingerprint changed")
        before = _candidate_evidence_snapshot(Path(candidate_path), contract)
        report = _run_evaluator(
            self.root / "evaluator.py", Path(candidate_path), self.timeout_seconds
        )
        after_evidence = _candidate_evidence_snapshot(Path(candidate_path), contract)
        if after_evidence != before:
            raise EvaluatorBundleError("frozen evaluator modified candidate evidence")
        after = load_evaluator_bundle(self.root, contract, timeout=self.timeout_seconds)
        if after.fingerprint != self.fingerprint:
            raise EvaluatorBundleError("frozen evaluator bundle changed during evaluation")
        return report


def compile_evaluator_bundle(
    runtime: Runtime | BundleRuntime,
    contract: AlgorithmProblemContract,
    workspace: Path,
    *,
    inputs: tuple[CandidateInputArtifact, ...] = (),
    timeout: float = 900.0,
) -> FrozenEvaluatorBundle:
    """Compile and preflight a bundle, or verify and reuse an existing frozen bundle."""
    if not isinstance(contract, AlgorithmProblemContract):
        raise TypeError("contract must be an AlgorithmProblemContract")
    timeout = _timeout(timeout)
    raw_root = Path(workspace).expanduser()
    if raw_root.is_symlink():
        raise EvaluatorBundleError("evaluator bundle workspace must not be a symlink")
    root = raw_root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "evaluator-bundle"
    if destination.exists() or destination.is_symlink():
        profile = _build_input_profile(root, contract, inputs)
        return load_evaluator_bundle(
            destination,
            contract,
            input_profile=profile,
            timeout=timeout,
        )

    compiler_workspace = root / ".evaluator-compiler"
    if compiler_workspace.is_symlink():
        raise EvaluatorBundleError("evaluator compiler workspace must not be a symlink")
    compiler_workspace.mkdir(parents=True, exist_ok=True)
    profile = _build_input_profile(root, contract, inputs)
    prompt = _compiler_prompt(contract, profile)
    try:
        result = _run_isolated(runtime, prompt, compiler_workspace, timeout)
    except Exception as exc:
        raise EvaluatorBundleError(f"evaluator compiler failed: {_error_category(exc)}") from exc
    if not isinstance(result, RuntimeResult):
        raise EvaluatorBundleError("evaluator compiler returned an invalid runtime result")
    envelope = _parse_envelope(result.text, contract)
    staging = Path(tempfile.mkdtemp(prefix=".evaluator-bundle-", dir=root))
    try:
        objective_path = staging / "objective.md"
        evaluator_path = staging / "evaluator.py"
        probes_path = staging / "probes.json"
        profile_path = staging / "input-profile.json"
        audit_path = staging / "audit.json"
        objective_path.write_text(envelope.objective + "\n", encoding="utf-8")
        evaluator_path.write_text(envelope.evaluator_source, encoding="utf-8")
        probes_path.write_text(_canonical_probe_suite(envelope.probe_suite()), encoding="utf-8")
        profile_path.write_text(canonical_profile_json(profile), encoding="utf-8")
        frozen_inputs = {
            path.name: _sha256(path)
            for path in (objective_path, evaluator_path, probes_path, profile_path)
        }
        _preflight(
            evaluator_path,
            envelope.probe_suite(),
            contract,
            staging,
            timeout,
            label="compiler",
        )
        current = tuple(staging.iterdir())
        if {path.name for path in current} != set(frozen_inputs) or any(
            path.is_symlink()
            or not path.is_file()
            or _sha256(path) != frozen_inputs[path.name]
            for path in current
        ):
            raise EvaluatorBundleError("evaluator preflight modified the frozen bundle inputs")
        audit_suite = _compile_audit_suite(
            runtime,
            contract,
            profile,
            envelope.objective,
            envelope.evaluator_source,
            root,
            timeout,
        )
        audit_path.write_text(_canonical_probe_suite(audit_suite), encoding="utf-8")
        frozen_inputs[audit_path.name] = _sha256(audit_path)
        _preflight(
            evaluator_path,
            audit_suite,
            contract,
            staging,
            timeout,
            label="audit",
        )
        current = tuple(staging.iterdir())
        if {path.name for path in current} != set(frozen_inputs) or any(
            path.is_symlink()
            or not path.is_file()
            or _sha256(path) != frozen_inputs[path.name]
            for path in current
        ):
            raise EvaluatorBundleError("evaluator audit modified the frozen bundle inputs")
        manifest = _manifest(
            contract,
            objective_path,
            evaluator_path,
            probes_path,
            audit_path,
            profile_path,
        )
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        for path in (
            objective_path,
            evaluator_path,
            probes_path,
            audit_path,
            profile_path,
            manifest_path,
        ):
            path.chmod(0o444)
        staging.chmod(0o555)
        load_evaluator_bundle(staging, contract, input_profile=profile, timeout=timeout)
        try:
            staging.replace(destination)
        except FileExistsError:
            _remove_tree(staging)
            return load_evaluator_bundle(
                destination, contract, input_profile=profile, timeout=timeout
            )
    except Exception:
        _remove_tree(staging)
        raise
    return load_evaluator_bundle(
        destination, contract, input_profile=profile, timeout=timeout
    )


def load_evaluator_bundle(
    root: Path,
    contract: AlgorithmProblemContract,
    *,
    input_profile: dict[str, object] | None = None,
    timeout: float = 900.0,
) -> FrozenEvaluatorBundle:
    """Load a frozen bundle after exact file, mode, schema, and digest verification."""
    timeout = _timeout(timeout)
    raw_root = Path(root).expanduser()
    if raw_root.is_symlink():
        raise EvaluatorBundleError("frozen evaluator bundle must not be a symlink")
    root = raw_root.resolve(strict=False)
    if not root.is_dir():
        raise EvaluatorBundleError("frozen evaluator bundle is missing")
    if root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise EvaluatorBundleError("frozen evaluator bundle directory is writable")
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise EvaluatorBundleError("frozen evaluator bundle is unreadable") from exc
    if {path.name for path in entries} != BUNDLE_FILES:
        raise EvaluatorBundleError("frozen evaluator bundle has an unexpected file set")
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise EvaluatorBundleError("frozen evaluator bundle contains an unsafe file")
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise EvaluatorBundleError("frozen evaluator bundle file is writable")
    manifest_path = root / "manifest.json"
    try:
        if manifest_path.stat().st_size > 16 * 1024:
            raise EvaluatorBundleError("frozen evaluator manifest exceeds the bounded size")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluatorBundleError("frozen evaluator manifest is invalid") from exc
    expected_keys = {
        "schema_version",
        "protocol",
        "contract_sha256",
        "objective_sha256",
        "evaluator_sha256",
        "probes_sha256",
        "audit_sha256",
        "input_profile_sha256",
        "bundle_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise EvaluatorBundleError("frozen evaluator manifest has an invalid shape")
    if manifest.get("schema_version") != "1" or manifest.get("protocol") != BUNDLE_PROTOCOL:
        raise EvaluatorBundleError("frozen evaluator manifest protocol is unsupported")
    if manifest.get("contract_sha256") != contract.digest():
        raise EvaluatorBundleError("frozen evaluator contract digest does not match")
    for name, key in (
        ("objective.md", "objective_sha256"),
        ("evaluator.py", "evaluator_sha256"),
        ("probes.json", "probes_sha256"),
        ("audit.json", "audit_sha256"),
        ("input-profile.json", "input_profile_sha256"),
    ):
        if _sha256(root / name) != manifest.get(key):
            raise EvaluatorBundleError(f"frozen evaluator {name} digest does not match")
    for name, label in (("probes.json", "compiler"), ("audit.json", "audit")):
        path = root / name
        try:
            stored_suite = _parse_probe_suite(path.read_text(encoding="utf-8"), contract, label=label)
            if path.read_text(encoding="utf-8") != _canonical_probe_suite(stored_suite):
                raise EvaluatorBundleError(f"frozen evaluator {label} suite is not canonical")
        except (OSError, UnicodeDecodeError) as exc:
            raise EvaluatorBundleError(f"frozen evaluator {label} suite is invalid") from exc
    profile_path = root / "input-profile.json"
    try:
        stored_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(stored_profile, dict):
            raise EvaluatorBundleError("frozen evaluator input profile has an invalid shape")
        if profile_path.read_text(encoding="utf-8") != canonical_profile_json(stored_profile):
            raise EvaluatorBundleError("frozen evaluator input profile is not canonical")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DataProfileError) as exc:
        raise EvaluatorBundleError("frozen evaluator input profile is invalid") from exc
    identity = {key: manifest[key] for key in expected_keys - {"bundle_sha256"}}
    if _dict_digest(identity) != manifest.get("bundle_sha256"):
        raise EvaluatorBundleError("frozen evaluator aggregate digest does not match")
    if input_profile is not None and profile_sha256(input_profile) != manifest.get(
        "input_profile_sha256"
    ):
        raise EvaluatorBundleError("frozen evaluator input profile digest does not match")
    try:
        source = (root / "evaluator.py").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvaluatorBundleError("frozen evaluator source is unreadable") from exc
    _validate_source(source)
    return FrozenEvaluatorBundle(
        root=root,
        fingerprint=manifest["bundle_sha256"],
        contract_sha256=manifest["contract_sha256"],
        input_profile_sha256=manifest["input_profile_sha256"],
        timeout_seconds=timeout,
    )


def _parse_envelope(raw: str, contract: AlgorithmProblemContract) -> EvaluatorBundleEnvelope:
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluatorBundleError("evaluator compiler returned empty output")
    if len(raw.encode("utf-8")) > MAX_BUNDLE_RESPONSE_BYTES:
        raise EvaluatorBundleError("evaluator compiler response exceeds the bounded size")
    if _SECRET.search(raw):
        raise EvaluatorBundleError("evaluator compiler response contains credential-like content")
    try:
        payload = _strict_json_loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise EvaluatorBundleError("evaluator compiler must return one strict JSON object") from exc
    expected = {
        "schema_version",
        "objective",
        "evaluator_source",
        "constraint_coverage",
        "probes",
        "score_order",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise EvaluatorBundleError("evaluator bundle envelope has an invalid shape")
    if payload["schema_version"] != "1":
        raise EvaluatorBundleError("evaluator bundle schema_version must be '1'")
    objective = _text(payload["objective"], "evaluator objective", MAX_OBJECTIVE_BYTES)
    source = _text(payload["evaluator_source"], "evaluator source", MAX_EVALUATOR_BYTES)
    _validate_source(source)
    probes = _parse_probes(payload["probes"], _required_probe_paths(contract))
    suite = _validate_probe_suite(
        payload["constraint_coverage"], probes, payload["score_order"], contract
    )
    return EvaluatorBundleEnvelope(
        objective,
        source,
        suite.constraint_coverage,
        suite.probes,
        suite.score_order,
    )


def _parse_probe_suite(
    raw: str, contract: AlgorithmProblemContract, *, label: str = "audit"
) -> ProbeSuite:
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluatorBundleError(f"evaluator {label} returned empty output")
    if len(raw.encode("utf-8")) > MAX_BUNDLE_RESPONSE_BYTES:
        raise EvaluatorBundleError(f"evaluator {label} response exceeds the bounded size")
    if _SECRET.search(raw):
        raise EvaluatorBundleError(
            f"evaluator {label} response contains credential-like content"
        )
    try:
        payload = _strict_json_loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise EvaluatorBundleError(
            f"evaluator {label} must return one strict JSON object"
        ) from exc
    expected = {"schema_version", "constraint_coverage", "probes", "score_order"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise EvaluatorBundleError(f"evaluator {label} suite has an invalid shape")
    if payload["schema_version"] != "1":
        raise EvaluatorBundleError(f"evaluator {label} schema_version must be '1'")
    required_probe_paths = _required_probe_paths(contract)
    probes = _parse_probes(payload["probes"], required_probe_paths)
    return _validate_probe_suite(
        payload["constraint_coverage"], probes, payload["score_order"], contract, label=label
    )


def _required_probe_paths(contract: AlgorithmProblemContract) -> frozenset[str]:
    return frozenset(
        [
            *(f"data/raw/{item.path}" for item in contract.inputs),
            *(item.path for item in contract.outputs if item.required),
        ]
    )


def _validate_probe_suite(
    coverage_value: object,
    probes: tuple[EvaluatorProbe, ...],
    orders_value: object,
    contract: AlgorithmProblemContract,
    *,
    label: str = "evaluator",
) -> ProbeSuite:
    constraint_ids = tuple(item.id for item in contract.hard_constraints)
    coverage = _string_array(coverage_value, f"{label} constraint coverage")
    if len(coverage) != len(set(coverage)) or set(coverage) != set(constraint_ids):
        raise EvaluatorBundleError(
            f"{label} constraint coverage must exactly match hard constraints"
        )
    valid_names = {probe.name for probe in probes if probe.expected_validity == 1}
    invalid_by_constraint = [
        probe.constraint_id for probe in probes if probe.expected_validity == 0
    ]
    if len(valid_names) < 2:
        raise EvaluatorBundleError(f"{label} requires at least two valid probes")
    if sorted(value for value in invalid_by_constraint if value is not None) != sorted(
        constraint_ids
    ) or any(
        probe.constraint_id is None for probe in probes if probe.expected_validity == 0
    ):
        raise EvaluatorBundleError(
            f"{label} constraint probe coverage must exactly match hard constraints"
        )
    if any(
        probe.constraint_id is not None for probe in probes if probe.expected_validity == 1
    ):
        raise EvaluatorBundleError(f"valid {label} probes cannot name a constraint")
    orders = _parse_score_order(orders_value, valid_names)
    return ProbeSuite(coverage, probes, orders)


def _parse_probes(
    value: object, required_paths: frozenset[str]
) -> tuple[EvaluatorProbe, ...]:
    if not isinstance(value, list) or not 2 <= len(value) <= MAX_PROBES:
        raise EvaluatorBundleError("evaluator probes must be a bounded array")
    probes: list[EvaluatorProbe] = []
    total_bytes = 0
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "constraint_id",
            "expected_validity",
            "files",
        }:
            raise EvaluatorBundleError("evaluator probe has an invalid shape")
        name = _identifier(raw["name"], "evaluator probe name")
        constraint_id = raw["constraint_id"]
        if constraint_id is not None:
            constraint_id = _identifier(constraint_id, "evaluator probe constraint_id")
        validity = raw["expected_validity"]
        if validity not in {0, 1} or isinstance(validity, bool):
            raise EvaluatorBundleError("evaluator probe expected_validity must be 0 or 1")
        raw_files = raw["files"]
        if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_PROBE_FILES:
            raise EvaluatorBundleError("evaluator probe files must be a bounded array")
        files: list[ProbeFile] = []
        for raw_file in raw_files:
            if not isinstance(raw_file, dict) or set(raw_file) != {"path", "content"}:
                raise EvaluatorBundleError("evaluator probe file has an invalid shape")
            path = _probe_path(raw_file["path"])
            content = _text(
                raw_file["content"], "evaluator probe content", MAX_PROBE_FILE_BYTES, strip=False
            )
            total_bytes += len(content.encode("utf-8"))
            files.append(ProbeFile(path, content))
        if len({item.path for item in files}) != len(files):
            raise EvaluatorBundleError("evaluator probe file paths must be unique")
        missing = required_paths - {item.path for item in files}
        if missing:
            raise EvaluatorBundleError(
                "evaluator probe must include every declared input and required output"
            )
        probes.append(EvaluatorProbe(name, constraint_id, validity, tuple(files)))
    if len({probe.name for probe in probes}) != len(probes):
        raise EvaluatorBundleError("evaluator probe names must be unique")
    if total_bytes > MAX_PROBE_BYTES:
        raise EvaluatorBundleError("evaluator probes exceed the aggregate content limit")
    return tuple(probes)


def _parse_score_order(value: object, valid_names: set[str]) -> tuple[ScoreOrder, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PROBES:
        raise EvaluatorBundleError("evaluator score order must be a bounded array")
    result: list[ScoreOrder] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"better", "worse"}:
            raise EvaluatorBundleError("evaluator score order has an invalid shape")
        better = _identifier(raw["better"], "better probe")
        worse = _identifier(raw["worse"], "worse probe")
        if better == worse or better not in valid_names or worse not in valid_names:
            raise EvaluatorBundleError("score order must reference two distinct valid probes")
        result.append(ScoreOrder(better, worse))
    return tuple(result)


def _validate_source(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise EvaluatorBundleError("evaluator source is not valid Python") from exc
    has_entrypoint = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name.split(".", 1)[0] for alias in node.names]
                if isinstance(node, ast.Import)
                else [(node.module or "").split(".", 1)[0]]
            )
            if not names or any(name not in _ALLOWED_IMPORTS for name in names):
                raise EvaluatorBundleError("evaluator source contains a forbidden import")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and (node.func.id in _DANGEROUS_CALLS or node.func.id == "__import__")
        ):
            raise EvaluatorBundleError("evaluator source contains forbidden dynamic execution")
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            rendered = ast.unparse(node.test)
            if "__name__" in rendered and "__main__" in rendered:
                has_entrypoint = True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value.startswith(("/", "~", "../")) or "/../" in value:
                raise EvaluatorBundleError("evaluator source contains a forbidden external path")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__")
            or node.attr == "modules"
            or node.attr in _DANGEROUS_ATTRIBUTES
        ):
            raise EvaluatorBundleError("evaluator source contains a forbidden attribute")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
        ):
            modes = [
                argument.value
                for argument in node.args[:1]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            ]
            modes.extend(
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "mode"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
            if any(mode not in {"r", "rt", "rb"} for mode in modes):
                raise EvaluatorBundleError("evaluator source contains a writable file open")
    if not has_entrypoint:
        raise EvaluatorBundleError("evaluator source requires a normal script entry point")


def _preflight(
    evaluator: Path,
    suite: ProbeSuite,
    contract: AlgorithmProblemContract,
    staging: Path,
    timeout: float,
    *,
    label: str,
) -> None:
    reports: dict[str, EvaluationReport] = {}
    probe_root = staging / f".{label}-preflight"
    for probe in suite.probes:
        workspace = probe_root / probe.name
        workspace.mkdir(parents=True)
        candidate = workspace / "candidate.py"
        candidate.write_text("# synthetic evaluator probe\n", encoding="utf-8")
        for item in probe.files:
            target = workspace / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")
        (workspace / "execution.json").write_text(
            json.dumps(
                CandidateExecution("succeeded", 0, 0).to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        rules = [
            {
                "output_valid": {
                    "path": output.path,
                    "format": output.format,
                    "fields": list(output.fields),
                }
            }
            for output in contract.outputs
            if output.required
        ]
        if rules:
            validator = acceptance_evaluator(
                rules[0] if len(rules) == 1 else {"all": rules}
            )
            if validator is None or not validator.evaluate("", workspace).passed:
                raise EvaluatorBundleError(
                    f"{label} probe {probe.name} violates the declared output schema"
                )
        report = _run_evaluator(evaluator, candidate, timeout)
        if report.validity != probe.expected_validity:
            raise EvaluatorBundleError(
                f"{label} constraint probe {probe.name} returned wrong validity"
            )
        if probe.constraint_id is not None and not any(
            item.get("code") == probe.constraint_id for item in report.error_info
        ):
            raise EvaluatorBundleError(
                f"{label} constraint probe {probe.name} did not report {probe.constraint_id}"
            )
        reports[probe.name] = report
    for order in suite.score_order:
        if not (
            reports[order.better].combined_score
            > reports[order.worse].combined_score
        ):
            raise EvaluatorBundleError(
                f"{label} score order failed: {order.better} must beat {order.worse}"
            )
    shutil.rmtree(probe_root)


def _run_evaluator(evaluator: Path, candidate: Path, timeout: float) -> EvaluationReport:
    if not candidate.is_file() or candidate.is_symlink():
        raise EvaluatorBundleError("evaluator candidate path is missing or unsafe")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(evaluator), str(candidate)],
            cwd=candidate.parent,
            env={
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONHASHSEED": "0",
                "PYTHONIOENCODING": "utf-8",
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvaluatorBundleError("frozen evaluator timed out") from exc
    except OSError as exc:
        raise EvaluatorBundleError("frozen evaluator could not start") from exc
    if completed.returncode != 0:
        raise EvaluatorBundleError("frozen evaluator exited unsuccessfully")
    if (
        len(completed.stdout.encode("utf-8")) > MAX_EVALUATOR_OUTPUT_BYTES
        or len(completed.stderr.encode("utf-8")) > MAX_EVALUATOR_OUTPUT_BYTES
    ):
        raise EvaluatorBundleError("frozen evaluator output exceeds the bounded size")
    try:
        payload = json.loads(completed.stdout)
        return EvaluationReport.from_dict(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EvaluatorBundleError("frozen evaluator returned an invalid EvaluationReport") from exc


def _candidate_evidence_snapshot(
    candidate: Path, contract: AlgorithmProblemContract
) -> dict[str, str | None]:
    """Bind evaluator-visible authoritative files so scoring cannot rewrite its own evidence."""
    raw_candidate = candidate.expanduser()
    if raw_candidate.is_symlink() or not raw_candidate.is_file():
        raise EvaluatorBundleError("evaluator candidate path is missing or unsafe")
    root = raw_candidate.parent.resolve(strict=False)
    paths = [
        raw_candidate,
        root / "execution.json",
        *(root / "data" / "raw" / item.path for item in contract.inputs),
        *(root / item.path for item in contract.outputs),
    ]
    snapshot: dict[str, str | None] = {}
    for path in paths:
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvaluatorBundleError("candidate evidence escapes its workspace") from exc
        if path.is_symlink():
            raise EvaluatorBundleError("candidate evidence contains a symlink")
        current = path
        while current != root:
            if current.is_symlink():
                raise EvaluatorBundleError("candidate evidence contains a symlink")
            current = current.parent
        if not path.exists():
            snapshot[relative] = None
            continue
        if not path.is_file():
            raise EvaluatorBundleError("candidate evidence is not a regular file")
        snapshot[relative] = _sha256(path)
    return snapshot


def _manifest(
    contract: AlgorithmProblemContract,
    objective: Path,
    evaluator: Path,
    probes: Path,
    audit: Path,
    input_profile: Path,
) -> dict[str, str]:
    identity = {
        "schema_version": "1",
        "protocol": BUNDLE_PROTOCOL,
        "contract_sha256": contract.digest(),
        "objective_sha256": _sha256(objective),
        "evaluator_sha256": _sha256(evaluator),
        "probes_sha256": _sha256(probes),
        "audit_sha256": _sha256(audit),
        "input_profile_sha256": _sha256(input_profile),
    }
    return {**identity, "bundle_sha256": _dict_digest(identity)}


def _build_input_profile(
    root: Path,
    contract: AlgorithmProblemContract,
    inputs: tuple[CandidateInputArtifact, ...],
) -> dict[str, object]:
    try:
        return build_private_input_profile(root, contract, inputs)
    except DataProfileError as exc:
        raise EvaluatorBundleError(str(exc)) from exc


def _compiler_prompt(
    contract: AlgorithmProblemContract, input_profile: dict[str, object]
) -> str:
    context = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    profile = json.dumps(input_profile, ensure_ascii=False, sort_keys=True, indent=2)
    profile_digest = profile_sha256(input_profile)
    return (
        "You are compiling one frozen local evaluator bundle for a bounded algorithm evolution. "
        "Return exactly one JSON object with schema_version='1', objective, evaluator_source, "
        "constraint_coverage, probes, and score_order. The Python evaluator receives a candidate "
        "path whose sibling workspace already contains verified data/raw, output, and "
        "execution.json. It must independently recompute every hard constraint and objective from "
        "those files, print exactly one strict EvaluationReport, use only deterministic standard "
        "library modules, and include an if __name__ == '__main__' entry point. combined_score is "
        "always higher-is-better. Provide exactly one expected_validity=0 synthetic probe per hard "
        "constraint with matching constraint_id/error_info.code, at least two valid probes, and at "
        "least one strict better/worse score_order assertion. Probe files may exist only under "
        "data/raw/ or output/. Do not return markdown, commands, credentials, or external paths.\n\n"
        "The private input profile contains structural counts and types only. Use observed fields "
        "to align parsing, but do not infer business semantics or constraints from missing values.\n\n"
        f"Canonical contract:\n{context}\n\n"
        f"Private input profile SHA-256: {profile_digest}\n"
        f"Private input profile:\n{profile}"
    )


def _compile_audit_suite(
    runtime: Runtime | BundleRuntime,
    contract: AlgorithmProblemContract,
    input_profile: dict[str, object],
    objective: str,
    evaluator_source: str,
    root: Path,
    timeout: float,
) -> ProbeSuite:
    workspace = root / ".evaluator-auditor"
    if workspace.is_symlink():
        raise EvaluatorBundleError("evaluator auditor workspace must not be a symlink")
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        result = _run_isolated(
            runtime,
            _auditor_prompt(contract, input_profile, objective, evaluator_source),
            workspace,
            timeout,
        )
    except Exception as exc:
        raise EvaluatorBundleError(f"evaluator auditor failed: {_error_category(exc)}") from exc
    if not isinstance(result, RuntimeResult):
        raise EvaluatorBundleError("evaluator auditor returned an invalid runtime result")
    return _parse_probe_suite(result.text, contract)


def _run_isolated(
    runtime: Runtime | BundleRuntime,
    prompt: str,
    workspace: Path,
    timeout: float,
) -> RuntimeResult:
    isolated = getattr(runtime, "run_isolated", None)
    if callable(isolated):
        return isolated(prompt, workspace, timeout)
    return runtime.run(prompt, workspace, timeout)


def _auditor_prompt(
    contract: AlgorithmProblemContract,
    input_profile: dict[str, object],
    objective: str,
    evaluator_source: str,
) -> str:
    context = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    profile = json.dumps(input_profile, ensure_ascii=False, sort_keys=True, indent=2)
    return (
        "You are an independent adversarial evaluator auditor. Attack the supplied frozen evaluator "
        "before any solver candidate exists. Return exactly one JSON object with schema_version='1', "
        "constraint_coverage, probes, and score_order. Provide exactly one expected_validity=0 probe "
        "per hard constraint, at least two valid probes, and at least one strict better/worse score "
        "ordering. Probe boundary cases, duplicate/omitted entities, and false rejection where relevant. "
        "Each probe must include every declared input and required output, using only relative paths "
        "below data/raw/ or output/. Do not return evaluator code, fixes, markdown, credentials, commands, "
        "external paths, or prose. The private profile contains structure only; never invent or request raw "
        "values. You have deliberately not received the compiler's self probes.\n\n"
        f"Canonical contract:\n{context}\n\n"
        f"Private input profile SHA-256: {profile_sha256(input_profile)}\n"
        f"Private input profile:\n{profile}\n\n"
        f"Frozen objective:\n{objective}\n\n"
        f"Frozen evaluator source:\n{evaluator_source}"
    )


def _canonical_probe_suite(suite: ProbeSuite) -> str:
    return json.dumps(
        suite.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _strict_json_loads(raw: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _probe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise EvaluatorBundleError("evaluator probe path is invalid")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvaluatorBundleError("evaluator probe path must be relative")
    relative = path.as_posix()
    if not relative.startswith(("data/raw/", "output/")):
        raise EvaluatorBundleError("evaluator probe path must be below data/raw/ or output/")
    return relative


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise EvaluatorBundleError(f"{field} must be a safe identifier")
    if len(value.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise EvaluatorBundleError(f"{field} exceeds the bounded size")
    return value


def _string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_PROBES:
        raise EvaluatorBundleError(f"{field} must be a bounded string array")
    return tuple(_identifier(item, field) for item in value)


def _text(
    value: object, field: str, limit: int, *, strip: bool = True
) -> str:
    if not isinstance(value, str):
        raise EvaluatorBundleError(f"{field} must be text")
    normalized = value.strip() if strip else value
    if not normalized or "\x00" in normalized:
        raise EvaluatorBundleError(f"{field} must be non-empty text")
    if len(normalized.encode("utf-8")) > limit:
        raise EvaluatorBundleError(f"{field} exceeds the bounded size")
    if _SECRET.search(normalized):
        raise EvaluatorBundleError(f"{field} contains credential-like content")
    return normalized


def _timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError("evaluator bundle timeout must be positive")
    return float(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dict_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _error_category(error: Exception) -> str:
    del error
    return "runtime_error"


def _remove_tree(path: Path) -> None:
    """Remove a private staging tree even after it was made read-only for final verification."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o700)
            for child in path.rglob("*"):
                if child.is_dir() and not child.is_symlink():
                    child.chmod(0o700)
                elif child.exists() and not child.is_symlink():
                    child.chmod(0o600)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "EvaluatorBundleError",
    "FrozenEvaluatorBundle",
    "compile_evaluator_bundle",
    "load_evaluator_bundle",
]
