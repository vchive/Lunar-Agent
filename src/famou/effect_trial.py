"""Small, frozen normal-Agent trials against exported Famou-Bench history.

This module is intentionally independent from Lunar's evolution strategies.  It stages a strict
public case projection, invokes one explicit normal-Agent subject, delegates all scoring to a
separate exact-harness command, and derives a descriptive single-case breakthrough milestone.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_CASES = 2
MAX_RUNS_PER_CASE = 10
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_PUBLIC_FILES = 128
MAX_PUBLIC_FILE_BYTES = 512 * 1024 * 1024
MAX_PATH_BYTES = 1024
MAX_COMMAND_ARGS = 32
MAX_TEXT_BYTES = 512
MAX_TOKENS = 100_000_000_000
MAX_TURNS = 100_000
MAX_TIMEOUT_SECONDS = 86_400.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MODEL_EVIDENCE = {"not_observable", "owner_attested", "runtime_observed", "provider_observed"}
_LIMITATIONS = (
    "selected_cases_do_not_establish_suite_parity",
    "best_of_n_is_not_a_statistical_superiority_test",
    "normal_mode_does_not_measure_deep_evolution",
    "process_capability_separation_is_not_an_os_sandbox",
)


class EffectTrialError(ValueError):
    """A frozen suite, process receipt, or recovery boundary is invalid."""


def _strict_object(value: object, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EffectTrialError(f"{label} must be an object")
    keys = set(value)
    missing = required - keys
    extra = keys - required
    if missing:
        raise EffectTrialError(f"{label} is missing required fields: {', '.join(sorted(missing))}")
    if extra:
        raise EffectTrialError(f"{label} contains unsupported fields: {', '.join(sorted(extra))}")
    return value


def _text(value: object, label: str, *, safe_id: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise EffectTrialError(f"{label} must be bounded non-empty text")
    if "\x00" in value:
        raise EffectTrialError(f"{label} contains an invalid character")
    if safe_id and not _SAFE_ID.fullmatch(value):
        raise EffectTrialError(f"{label} must be a safe identifier")
    return value


def _digest(value: object, label: str, *, prefixed: bool = False) -> str:
    pattern = _OBJECT_SHA256 if prefixed else _SHA256
    if not isinstance(value, str) or not pattern.fullmatch(value):
        prefix = "sha256:-prefixed " if prefixed else ""
        raise EffectTrialError(f"{label} must be a lowercase {prefix}SHA-256 digest")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EffectTrialError(f"{label} must be between {minimum} and {maximum}")
    return value


def _number(value: object, label: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EffectTrialError(f"{label} must be finite" + (" or null" if nullable else ""))
    return float(value)


def _validity(value: object, label: str, *, nullable: bool = False) -> float | None:
    number = _number(value, label, nullable=nullable)
    if number is not None and not 0.0 <= number <= 1.0:
        raise EffectTrialError(f"{label} must be between zero and one")
    return number


def _relative_path(value: object, label: str) -> str:
    text = _text(value, label)
    if "\\" in text or len(text.encode("utf-8")) > MAX_PATH_BYTES:
        raise EffectTrialError(f"{label} must be a bounded POSIX relative path")
    path = Path(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EffectTrialError(f"{label} must be a confined relative path")
    return path.as_posix()


def _private_path(path: str) -> bool:
    parts = Path(path).parts
    lowered = tuple(part.lower() for part in parts)
    basename = lowered[-1]
    return bool(
        lowered[0] in {"tests", ".harness"}
        or "tests" in lowered
        or ".harness" in lowered
        or basename == "gt.json"
        or "evaluator" in basename
        or "extractor" in basename
    )


def _canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_command(command: Sequence[str]) -> str:
    file_identities: list[dict[str, object]] = []
    for index, value in enumerate(command):
        path = Path(value)
        if path.is_absolute() and not path.is_symlink() and path.is_file():
            hasher = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    hasher.update(chunk)
            file_identities.append({"argument_index": index, "size": size, "sha256": hasher.hexdigest()})
    return _hash_bytes(_canonical_bytes({"arguments": list(command), "files": file_identities}))


def _read_json(path: Path, label: str, maximum: int = MAX_MANIFEST_BYTES) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise EffectTrialError(f"{label} must be a regular non-symlink file")
    content = path.read_bytes()
    if not content or len(content) > maximum:
        raise EffectTrialError(f"{label} exceeds its bounded size")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EffectTrialError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise EffectTrialError(f"{label} must contain a JSON object")
    return payload, _canonical_bytes(payload)


def _atomic_json(path: Path, payload: object, maximum: int = MAX_MANIFEST_BYTES) -> bytes:
    content = _canonical_bytes(payload)
    if len(content) > maximum:
        raise EffectTrialError(f"{path.name} exceeds its bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EffectTrialError(f"{path.name} must not be a symlink")
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.is_symlink():
        raise EffectTrialError(f"{path.name} temporary path must not be a symlink")
    temporary.write_bytes(content)
    os.replace(temporary, path)
    return content


def _reject_symlink_components(path: Path, root: Path, label: str) -> None:
    current = path
    root = root.resolve()
    while current != root and current != current.parent:
        if current.is_symlink():
            raise EffectTrialError(f"{label} contains a symlink")
        current = current.parent


@dataclass(frozen=True)
class PublicFile:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, payload: object) -> PublicFile:
        item = _strict_object(payload, {"path", "size", "sha256"}, "public file")
        path = _relative_path(item["path"], "public file path")
        if _private_path(path):
            raise EffectTrialError(f"public file path exposes a private harness path: {path}")
        return cls(
            path=path,
            size=_integer(item["size"], "public file size", 0, MAX_PUBLIC_FILE_BYTES),
            sha256=_digest(item["sha256"], "public file sha256"),
        )

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class HarnessIdentity:
    extractor_sha256: str
    evaluator_sha256: str

    @classmethod
    def from_dict(cls, payload: object) -> HarnessIdentity:
        item = _strict_object(payload, {"extractor_sha256", "evaluator_sha256"}, "harness identity")
        return cls(
            _digest(item["extractor_sha256"], "extractor sha256"),
            _digest(item["evaluator_sha256"], "evaluator sha256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"extractor_sha256": self.extractor_sha256, "evaluator_sha256": self.evaluator_sha256}


@dataclass(frozen=True)
class BenchmarkIdentity:
    name: str
    release_version: str
    publication_digest: str

    @classmethod
    def from_dict(cls, payload: object) -> BenchmarkIdentity:
        item = _strict_object(payload, {"name", "release_version", "publication_digest"}, "benchmark identity")
        return cls(
            _text(item["name"], "benchmark name", safe_id=True),
            _text(item["release_version"], "benchmark release version", safe_id=True),
            _digest(item["publication_digest"], "publication digest", prefixed=True),
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "release_version": self.release_version, "publication_digest": self.publication_digest}


@dataclass(frozen=True)
class EvaluationProfileIdentity:
    name: str
    revision: int
    digest: str

    @classmethod
    def from_dict(cls, payload: object) -> EvaluationProfileIdentity:
        item = _strict_object(payload, {"name", "revision", "digest"}, "evaluation profile")
        return cls(
            _text(item["name"], "evaluation profile name", safe_id=True),
            _integer(item["revision"], "evaluation profile revision", 1, 1_000_000),
            _digest(item["digest"], "evaluation profile digest", prefixed=True),
        )

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "revision": self.revision, "digest": self.digest}


@dataclass(frozen=True)
class TrialCase:
    key: str
    revision_id: str
    digest: str
    entrypoint: str
    public_files: tuple[PublicFile, ...]
    harness: HarnessIdentity

    @classmethod
    def from_dict(cls, payload: object) -> TrialCase:
        item = _strict_object(
            payload,
            {"key", "revision_id", "digest", "entrypoint", "public_files", "harness"},
            "suite case",
        )
        raw_files = item["public_files"]
        if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_PUBLIC_FILES:
            raise EffectTrialError("suite case public_files must be a bounded non-empty array")
        files = tuple(PublicFile.from_dict(value) for value in raw_files)
        paths = [value.path for value in files]
        if len(paths) != len(set(paths)):
            raise EffectTrialError("suite case public file paths must be unique")
        entrypoint = _relative_path(item["entrypoint"], "case entrypoint")
        if _private_path(entrypoint) or entrypoint not in set(paths):
            raise EffectTrialError("case entrypoint must name a public non-private ledger file")
        return cls(
            key=_text(item["key"], "case key", safe_id=True),
            revision_id=_text(item["revision_id"], "case revision id", safe_id=True),
            digest=_digest(item["digest"], "case digest", prefixed=True),
            entrypoint=entrypoint,
            public_files=files,
            harness=HarnessIdentity.from_dict(item["harness"]),
        )

    def public_identity(self) -> dict[str, str]:
        return {"key": self.key, "revision_id": self.revision_id, "digest": self.digest}

    def to_dict(self) -> dict[str, object]:
        return {
            **self.public_identity(),
            "entrypoint": self.entrypoint,
            "public_files": [value.to_dict() for value in self.public_files],
            "harness": self.harness.to_dict(),
        }


@dataclass(frozen=True)
class TrialSuite:
    benchmark: BenchmarkIdentity
    evaluation_profile: EvaluationProfileIdentity
    cases: tuple[TrialCase, ...]

    @classmethod
    def from_dict(cls, payload: object) -> TrialSuite:
        item = _strict_object(payload, {"schema_version", "benchmark", "evaluation_profile", "cases"}, "suite manifest")
        if item["schema_version"] != "1":
            raise EffectTrialError("suite schema_version must be '1'")
        raw_cases = item["cases"]
        if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= MAX_CASES:
            raise EffectTrialError("suite must select exactly one or two cases")
        cases = tuple(TrialCase.from_dict(value) for value in raw_cases)
        if len({value.key for value in cases}) != len(cases):
            raise EffectTrialError("suite case keys must be unique")
        return cls(
            BenchmarkIdentity.from_dict(item["benchmark"]),
            EvaluationProfileIdentity.from_dict(item["evaluation_profile"]),
            cases,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "benchmark": self.benchmark.to_dict(),
            "evaluation_profile": self.evaluation_profile.to_dict(),
            "cases": [value.to_dict() for value in self.cases],
        }


@dataclass(frozen=True)
class BaselineModel:
    requested: str
    effective: str
    evidence: str

    @classmethod
    def from_dict(cls, payload: object) -> BaselineModel:
        item = _strict_object(payload, {"requested", "effective", "evidence"}, "baseline model")
        evidence = _text(item["evidence"], "baseline model evidence", safe_id=True)
        if evidence not in _MODEL_EVIDENCE:
            raise EffectTrialError("baseline model evidence is unsupported")
        return cls(_text(item["requested"], "requested model"), _text(item["effective"], "effective model"), evidence)

    def to_dict(self) -> dict[str, str]:
        return {"requested": self.requested, "effective": self.effective, "evidence": self.evidence}


@dataclass(frozen=True)
class BaselineRun:
    run_index: int
    ready: bool
    extraction_status: str
    validity_score: float | None
    overall_score: float | None

    @classmethod
    def from_dict(cls, payload: object) -> BaselineRun:
        item = _strict_object(
            payload,
            {"run_index", "ready", "extraction_status", "validity_score", "overall_score"},
            "baseline run",
        )
        if not isinstance(item["ready"], bool):
            raise EffectTrialError("baseline run ready must be boolean")
        return cls(
            _integer(item["run_index"], "baseline run_index", 1, 1_000_000),
            item["ready"],
            _text(item["extraction_status"], "baseline extraction_status", safe_id=True),
            _validity(item["validity_score"], "baseline validity_score", nullable=True),
            _number(item["overall_score"], "baseline overall_score", nullable=True),
        )

    def eligible_score(self) -> float | None:
        if self.ready and self.extraction_status == "completed" and self.validity_score not in {None, 0.0}:
            return self.overall_score
        return None


@dataclass(frozen=True)
class BaselineCase:
    key: str
    revision_id: str
    digest: str
    harness: HarnessIdentity
    runs: tuple[BaselineRun, ...]

    @classmethod
    def from_dict(cls, payload: object) -> BaselineCase:
        item = _strict_object(payload, {"key", "revision_id", "digest", "harness", "runs"}, "baseline case")
        raw_runs = item["runs"]
        if not isinstance(raw_runs, list) or not raw_runs or len(raw_runs) > 10_000:
            raise EffectTrialError("baseline case runs must be a bounded non-empty array")
        runs = tuple(BaselineRun.from_dict(value) for value in raw_runs)
        if len({value.run_index for value in runs}) != len(runs):
            raise EffectTrialError("baseline run indexes must be unique")
        return cls(
            _text(item["key"], "baseline case key", safe_id=True),
            _text(item["revision_id"], "baseline case revision", safe_id=True),
            _digest(item["digest"], "baseline case digest", prefixed=True),
            HarnessIdentity.from_dict(item["harness"]),
            runs,
        )

    def best(self) -> float | None:
        scores = [score for run in self.runs if (score := run.eligible_score()) is not None]
        return max(scores) if scores else None


@dataclass(frozen=True)
class TrialBaseline:
    source: str
    experiment_id: str
    authority: str
    conclusion_eligibility: str
    benchmark: BenchmarkIdentity
    evaluation_profile: EvaluationProfileIdentity
    model: BaselineModel
    cases: tuple[BaselineCase, ...]

    @classmethod
    def from_dict(cls, payload: object) -> TrialBaseline:
        item = _strict_object(
            payload,
            {
                "schema_version", "source", "experiment_id", "authority",
                "conclusion_eligibility", "benchmark", "evaluation_profile", "model", "cases",
            },
            "baseline export",
        )
        if item["schema_version"] != "1" or item["source"] != "fm-eval":
            raise EffectTrialError("baseline must be a schema v1 fm-eval export")
        authority = _text(item["authority"], "baseline authority", safe_id=True)
        eligibility = _text(item["conclusion_eligibility"], "baseline conclusion eligibility", safe_id=True)
        if eligibility not in {"eligible", "ineligible"}:
            raise EffectTrialError("baseline conclusion eligibility is unsupported")
        raw_cases = item["cases"]
        if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 10_000:
            raise EffectTrialError("baseline cases must be a bounded non-empty array")
        cases = tuple(BaselineCase.from_dict(value) for value in raw_cases)
        if len({value.key for value in cases}) != len(cases):
            raise EffectTrialError("baseline case keys must be unique")
        return cls(
            source="fm-eval",
            experiment_id=_text(item["experiment_id"], "baseline experiment id", safe_id=True),
            authority=authority,
            conclusion_eligibility=eligibility,
            benchmark=BenchmarkIdentity.from_dict(item["benchmark"]),
            evaluation_profile=EvaluationProfileIdentity.from_dict(item["evaluation_profile"]),
            model=BaselineModel.from_dict(item["model"]),
            cases=cases,
        )


@dataclass(frozen=True)
class EffectTrialConfig:
    runs_per_case: int = 3
    timeout_seconds: float = 3600.0
    requested_model: str = ""
    subject_command: tuple[str, ...] = ()
    harness_command: tuple[str, ...] = ()
    subject_environment: Mapping[str, str] = field(default_factory=dict)
    harness_environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _integer(self.runs_per_case, "runs_per_case", 1, MAX_RUNS_PER_CASE)
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise EffectTrialError("timeout_seconds must be finite and within one day")
        _text(self.requested_model, "requested_model")
        for label, command in (("subject", self.subject_command), ("harness", self.harness_command)):
            if isinstance(command, (str, bytes)):
                raise EffectTrialError(f"{label} command must be an argument sequence")
            normalized = tuple(command)
            if not 1 <= len(normalized) <= MAX_COMMAND_ARGS or any(
                not isinstance(value, str) or not value or "\x00" in value or len(value.encode("utf-8")) > 4096
                for value in normalized
            ):
                raise EffectTrialError(f"{label} command must be a bounded argument sequence")
            executable = Path(normalized[0])
            if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
                raise EffectTrialError(f"{label} command executable must be an absolute regular non-symlink file")
            object.__setattr__(self, f"{label}_command", normalized)
        for label, environment in (("subject", self.subject_environment), ("harness", self.harness_environment)):
            if not isinstance(environment, Mapping) or len(environment) > 64:
                raise EffectTrialError(f"{label} environment must be a bounded mapping")
            normalized_env: dict[str, str] = {}
            for name, value in environment.items():
                if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                    raise EffectTrialError(f"{label} environment name is invalid")
                if not isinstance(value, str) or "\x00" in value or len(value.encode("utf-8")) > 16 * 1024:
                    raise EffectTrialError(f"{label} environment value is invalid")
                normalized_env[name] = value
            object.__setattr__(self, f"{label}_environment", normalized_env)

    def safe_dict(self) -> dict[str, object]:
        return {
            "runs_per_case": self.runs_per_case,
            "timeout_seconds": float(self.timeout_seconds),
            "requested_model": self.requested_model,
            "subject_command_sha256": _hash_command(self.subject_command),
            "harness_command_sha256": _hash_command(self.harness_command),
            "subject_env_names": sorted(self.subject_environment),
            "harness_env_names": sorted(self.harness_environment),
        }


@dataclass(frozen=True)
class EffectTrialReport:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))


ProcessExecutor = Callable[..., subprocess.CompletedProcess[Any]]


def _default_executor(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float) -> subprocess.CompletedProcess[Any]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    return subprocess.CompletedProcess(command, returncode)


class EffectTrialRunner:
    """Run a recoverable one/two-case normal-Agent effect trial."""

    def __init__(
        self,
        suite_path: str | Path,
        baseline_path: str | Path,
        workspace: str | Path,
        *,
        case_sources: Mapping[str, str | Path],
        config: EffectTrialConfig,
        resume: bool = False,
        process_executor: ProcessExecutor | None = None,
    ) -> None:
        suite_payload, suite_bytes = _read_json(Path(suite_path).expanduser(), "suite manifest")
        baseline_payload, baseline_bytes = _read_json(Path(baseline_path).expanduser(), "baseline export")
        self.suite = TrialSuite.from_dict(suite_payload)
        self.baseline = TrialBaseline.from_dict(baseline_payload)
        self.suite_bytes = suite_bytes
        self.baseline_bytes = baseline_bytes
        self.suite_sha256 = _hash_bytes(suite_bytes)
        self.baseline_sha256 = _hash_bytes(baseline_bytes)
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.config = config
        self.resume = resume
        self.process_executor = process_executor or _default_executor
        self._started = False
        if not isinstance(case_sources, Mapping):
            raise EffectTrialError("case_sources must be a mapping")
        expected = {value.key for value in self.suite.cases}
        if set(case_sources) != expected:
            raise EffectTrialError("case_sources must exactly match selected suite case keys")
        self.case_sources = {key: Path(value).expanduser() for key, value in case_sources.items()}
        self._validate_shared_identities()
        self._verify_sources()
        if self.workspace.exists():
            if self.workspace.is_symlink() or not self.workspace.is_dir():
                raise EffectTrialError("trial workspace must be a regular directory")
            if not resume and any(self.workspace.iterdir()):
                raise EffectTrialError("trial workspace is not empty; use resume explicitly")
        elif resume:
            raise EffectTrialError("cannot resume a missing trial workspace")

    def _validate_shared_identities(self) -> None:
        if self.baseline.benchmark != self.suite.benchmark:
            raise EffectTrialError("baseline benchmark identity does not match suite")
        if self.baseline.evaluation_profile != self.suite.evaluation_profile:
            raise EffectTrialError("baseline evaluation profile identity does not match suite")
        baseline_cases = {value.key: value for value in self.baseline.cases}
        for case in self.suite.cases:
            baseline = baseline_cases.get(case.key)
            if baseline is None:
                raise EffectTrialError(f"baseline does not cover selected case {case.key}")
            if (baseline.revision_id, baseline.digest, baseline.harness) != (
                case.revision_id,
                case.digest,
                case.harness,
            ):
                raise EffectTrialError(f"baseline case/harness identity does not match suite: {case.key}")
            if baseline.best() is None:
                raise EffectTrialError(f"baseline case has no evaluator-valid historical score: {case.key}")
        if self.baseline.model.requested != self.config.requested_model:
            raise EffectTrialError("requested model does not match the baseline model request")

    def _source_file(self, case: TrialCase, descriptor: PublicFile) -> Path:
        root_raw = self.case_sources[case.key]
        if root_raw.is_symlink() or not root_raw.is_dir():
            raise EffectTrialError(f"case source root is missing or a symlink: {case.key}")
        root = root_raw.resolve()
        raw = root / descriptor.path
        _reject_symlink_components(raw, root, f"case source {descriptor.path}")
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise EffectTrialError(f"case source path escapes root: {descriptor.path}") from exc
        if raw.is_symlink() or not resolved.is_file():
            raise EffectTrialError(f"case source file is missing or a symlink: {descriptor.path}")
        return resolved

    def _verify_sources(self) -> None:
        for case in self.suite.cases:
            for descriptor in case.public_files:
                source = self._source_file(case, descriptor)
                content = source.read_bytes()
                if len(content) != descriptor.size or _hash_bytes(content) != descriptor.sha256:
                    raise EffectTrialError(f"case source size/digest mismatch: {case.key}/{descriptor.path}")

    def _identity(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "protocol": "famou-bench-breakthrough-v1",
            "mode": "normal",
            "suite_sha256": self.suite_sha256,
            "baseline_sha256": self.baseline_sha256,
            "case_keys": [value.key for value in self.suite.cases],
            "config": self.config.safe_dict(),
        }

    def _state_path(self) -> Path:
        return self.workspace / "control" / "state.json"

    def _prepare_state(self) -> dict[str, Any]:
        identity = self._identity()
        if self.resume:
            state, _ = _read_json(self._state_path(), "trial state")
            item = _strict_object(state, {"identity", "records"}, "trial state")
            if item["identity"] != identity:
                raise EffectTrialError("resume configuration does not match frozen trial identity")
            records = item["records"]
            if not isinstance(records, dict) or any(
                not isinstance(key, str) or not isinstance(value, str) or not _SHA256.fullmatch(value)
                for key, value in records.items()
            ):
                raise EffectTrialError("trial state records are invalid")
            expected_keys = {
                self._record_key(case, run_index)
                for case in self.suite.cases
                for run_index in range(1, self.config.runs_per_case + 1)
            }
            if set(records) - expected_keys:
                raise EffectTrialError("trial state contains an unknown logical run record")
            self._verify_control_copy("suite.json", self.suite_sha256)
            self._verify_control_copy("baseline.json", self.baseline_sha256)
            return item
        self.workspace.mkdir(parents=True, exist_ok=True)
        control = self.workspace / "control"
        control.mkdir(parents=True, exist_ok=True)
        _atomic_json(control / "suite.json", self.suite.to_dict())
        _atomic_json(control / "baseline.json", json.loads(self.baseline_bytes))
        state = {"identity": identity, "records": {}}
        _atomic_json(self._state_path(), state)
        return state

    def _verify_control_copy(self, name: str, expected: str) -> None:
        payload, canonical = _read_json(self.workspace / "control" / name, f"frozen {name}")
        del payload
        if _hash_bytes(canonical) != expected:
            raise EffectTrialError(f"frozen {name} digest does not match trial identity")

    def _record_key(self, case: TrialCase, run_index: int) -> str:
        return f"{case.key}/{run_index:03d}"

    def _record_path(self, case: TrialCase, run_index: int) -> Path:
        return self.workspace / "cases" / case.key / "runs" / f"{run_index:03d}" / "record.json"

    def _load_record(self, case: TrialCase, run_index: int, state: dict[str, Any]) -> dict[str, Any] | None:
        path = self._record_path(case, run_index)
        key = self._record_key(case, run_index)
        if not path.exists():
            if key in state["records"]:
                raise EffectTrialError(f"logical run record is missing despite frozen state: {key}")
            return None
        payload, canonical = _read_json(path, "logical run record", MAX_RECEIPT_BYTES)
        expected = state["records"].get(key)
        actual = _hash_bytes(canonical)
        if expected is not None and actual != expected:
            raise EffectTrialError(f"logical run record digest mismatch: {key}")
        self._validate_record(payload, case, run_index)
        if expected is None:
            state["records"][key] = actual
            _atomic_json(self._state_path(), state)
        return payload

    def _validate_record(self, payload: object, case: TrialCase, run_index: int) -> dict[str, Any]:
        item = _strict_object(
            payload,
            {
                "schema_version", "case_key", "run_index", "attempt", "status", "ready",
                "elapsed_ms", "requested_model", "effective_model", "model_evidence",
                "interaction_turns", "usage", "extraction_status", "validity_score",
                "overall_score", "quality_score", "detail_metrics", "error_code",
            },
            "logical run record",
        )
        if item["schema_version"] != "1" or item["case_key"] != case.key or item["run_index"] != run_index:
            raise EffectTrialError("logical run record identity mismatch")
        _relative_path(item["attempt"], "logical run attempt")
        if item["status"] not in {"completed", "failed"} or not isinstance(item["ready"], bool):
            raise EffectTrialError("logical run record status is invalid")
        _integer(item["elapsed_ms"], "logical run elapsed_ms", 0, 172_800_000)
        for name in ("requested_model", "effective_model", "model_evidence", "extraction_status", "error_code"):
            value = item[name]
            if value is not None:
                _text(value, f"logical run {name}", safe_id=name in {"model_evidence", "extraction_status", "error_code"})
        if item["interaction_turns"] is not None:
            _integer(item["interaction_turns"], "logical run interaction_turns", 0, MAX_TURNS)
        if item["usage"] is not None:
            self._validate_usage(item["usage"])
        for name in ("validity_score", "overall_score", "quality_score"):
            _number(item[name], f"logical run {name}", nullable=True)
        if not isinstance(item["detail_metrics"], dict) or len(_canonical_bytes(item["detail_metrics"])) > 16 * 1024:
            raise EffectTrialError("logical run detail_metrics is invalid")
        return item

    @staticmethod
    def _environment(extra: Mapping[str, str]) -> dict[str, str]:
        return {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONUTF8": "1",
            **extra,
        }

    def _stage_public_case(self, case: TrialCase, subject_root: Path) -> None:
        case_root = subject_root / "case"
        case_root.mkdir(parents=True, exist_ok=True)
        for descriptor in case.public_files:
            source = self._source_file(case, descriptor)
            content = source.read_bytes()
            if len(content) != descriptor.size or _hash_bytes(content) != descriptor.sha256:
                raise EffectTrialError(f"case source size/digest mismatch: {case.key}/{descriptor.path}")
            target = case_root / descriptor.path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or target.exists():
                raise EffectTrialError(f"public target already exists or is unsafe: {descriptor.path}")
            target.write_bytes(content)

    def _verify_staged_case(self, case: TrialCase, subject_root: Path, request_sha256: str) -> None:
        request = subject_root / "request.json"
        if request.is_symlink() or not request.is_file() or _hash_bytes(request.read_bytes()) != request_sha256:
            raise EffectTrialError("subject changed the frozen request")
        case_root = (subject_root / "case").resolve(strict=False)
        for descriptor in case.public_files:
            raw = subject_root / "case" / descriptor.path
            _reject_symlink_components(raw, case_root, f"staged public file {descriptor.path}")
            if raw.is_symlink() or not raw.is_file():
                raise EffectTrialError(f"staged public file is missing or a symlink: {descriptor.path}")
            content = raw.read_bytes()
            if len(content) != descriptor.size or _hash_bytes(content) != descriptor.sha256:
                raise EffectTrialError(f"staged public file digest changed: {descriptor.path}")

    def _attempt_root(self, case: TrialCase, run_index: int) -> tuple[Path, int]:
        attempts = self._record_path(case, run_index).parent / "attempts"
        if attempts.is_symlink():
            raise EffectTrialError("logical run attempts directory must not be a symlink")
        attempts.mkdir(parents=True, exist_ok=True)
        children = list(attempts.iterdir())
        if any(path.is_symlink() for path in children):
            raise EffectTrialError("logical run attempt must not be a symlink")
        indexes = [int(path.name) for path in children if path.is_dir() and path.name.isdigit()]
        attempt_index = max(indexes, default=0) + 1
        root = attempts / f"{attempt_index:03d}"
        root.mkdir()
        return root, attempt_index

    def _invoke(self, command: tuple[str, ...], config_path: Path, *, cwd: Path, environment: Mapping[str, str]) -> None:
        try:
            result = self.process_executor(
                (*command, str(config_path)),
                cwd=cwd,
                env=self._environment(environment),
                timeout=float(self.config.timeout_seconds),
            )
        except subprocess.TimeoutExpired as exc:
            raise EffectTrialError("process_timeout") from exc
        except OSError as exc:
            raise EffectTrialError("process_start_failed") from exc
        if not isinstance(result, subprocess.CompletedProcess) and not hasattr(result, "returncode"):
            raise EffectTrialError("process_result_invalid")
        if result.returncode != 0:
            raise EffectTrialError("process_nonzero_exit")

    @staticmethod
    def _validate_usage(payload: object) -> dict[str, int] | None:
        if payload is None:
            return None
        item = _strict_object(payload, {"input_tokens", "output_tokens", "total_tokens"}, "token usage")
        values = {name: _integer(item[name], f"token usage {name}", 0, MAX_TOKENS) for name in item}
        if values["input_tokens"] + values["output_tokens"] != values["total_tokens"]:
            raise EffectTrialError("token usage total must equal input plus output")
        return values

    def _subject_receipt(self, path: Path) -> dict[str, Any]:
        payload, _ = _read_json(path, "subject receipt", MAX_RECEIPT_BYTES)
        item = _strict_object(
            payload,
            {"schema_version", "mode", "status", "requested_model", "effective_model", "model_evidence", "interaction_turns", "usage"},
            "subject receipt",
        )
        if item["schema_version"] != "1" or item["mode"] != "normal" or item["status"] != "completed":
            raise EffectTrialError("subject receipt does not describe a completed normal run")
        if item["requested_model"] != self.config.requested_model:
            raise EffectTrialError("subject requested model does not match frozen config")
        effective = _text(item["effective_model"], "subject effective model")
        evidence = _text(item["model_evidence"], "subject model evidence", safe_id=True)
        if evidence not in _MODEL_EVIDENCE:
            raise EffectTrialError("subject model evidence is unsupported")
        return {
            "requested_model": item["requested_model"],
            "effective_model": effective,
            "model_evidence": evidence,
            "interaction_turns": _integer(item["interaction_turns"], "subject interaction turns", 0, MAX_TURNS),
            "usage": self._validate_usage(item["usage"]),
        }

    def _harness_receipt(self, path: Path, case: TrialCase) -> dict[str, Any]:
        payload, _ = _read_json(path, "harness receipt", MAX_RECEIPT_BYTES)
        item = _strict_object(
            payload,
            {
                "schema_version", "status", "benchmark", "evaluation_profile", "case", "harness",
                "extraction_status", "validity_score", "overall_score", "quality_score", "detail_metrics",
            },
            "harness receipt",
        )
        if item["schema_version"] != "1" or item["status"] != "completed":
            raise EffectTrialError("harness receipt does not describe a completed evaluation")
        if BenchmarkIdentity.from_dict(item["benchmark"]) != self.suite.benchmark:
            raise EffectTrialError("harness receipt benchmark identity mismatch")
        if EvaluationProfileIdentity.from_dict(item["evaluation_profile"]) != self.suite.evaluation_profile:
            raise EffectTrialError("harness receipt evaluation profile identity mismatch")
        receipt_case = _strict_object(item["case"], {"key", "revision_id", "digest"}, "harness receipt case")
        if receipt_case != case.public_identity():
            raise EffectTrialError("harness receipt case identity mismatch")
        if HarnessIdentity.from_dict(item["harness"]) != case.harness:
            raise EffectTrialError("harness receipt harness identity mismatch")
        extraction = _text(item["extraction_status"], "harness extraction status", safe_id=True)
        validity = _validity(item["validity_score"], "harness validity score", nullable=True)
        overall = _number(item["overall_score"], "harness overall score", nullable=True)
        quality = _number(item["quality_score"], "harness quality score", nullable=True)
        if extraction == "completed" and (validity is None or overall is None):
            raise EffectTrialError("completed harness extraction requires validity and overall score")
        if extraction != "completed" and (
            validity not in {None, 0.0} or overall not in {None, 0.0}
        ):
            raise EffectTrialError("incomplete harness extraction cannot carry a valid score")
        details = item["detail_metrics"]
        if not isinstance(details, dict) or len(_canonical_bytes(details)) > 16 * 1024:
            raise EffectTrialError("harness detail_metrics is invalid")
        for key, value in details.items():
            _text(key, "harness detail metric name", safe_id=True)
            _number(value, f"harness detail metric {key}", nullable=True)
        return {
            "extraction_status": extraction,
            "validity_score": validity,
            "overall_score": overall,
            "quality_score": quality,
            "detail_metrics": details,
        }

    def _failed_record(self, case: TrialCase, run_index: int, attempt_index: int, started: float, code: str) -> dict[str, Any]:
        return {
            "schema_version": "1", "case_key": case.key, "run_index": run_index,
            "attempt": f"cases/{case.key}/runs/{run_index:03d}/attempts/{attempt_index:03d}",
            "status": "failed", "ready": False, "elapsed_ms": self._elapsed(started),
            "requested_model": self.config.requested_model, "effective_model": None,
            "model_evidence": None, "interaction_turns": None, "usage": None,
            "extraction_status": None, "validity_score": None, "overall_score": None,
            "quality_score": None, "detail_metrics": {}, "error_code": code,
        }

    @staticmethod
    def _elapsed(started: float) -> int:
        return min(172_800_000, max(0, int((time.monotonic() - started) * 1000)))

    def _execute_run(self, case: TrialCase, run_index: int) -> dict[str, Any]:
        attempt_root, attempt_index = self._attempt_root(case, run_index)
        subject_root = attempt_root / "subject"
        harness_root = attempt_root / "harness"
        subject_root.mkdir()
        started = time.monotonic()
        try:
            self._stage_public_case(case, subject_root)
            subject_request = {
                "schema_version": "1", "mode": "normal",
                "benchmark": self.suite.benchmark.to_dict(), "case": case.public_identity(),
                "run_index": run_index, "requested_model": self.config.requested_model,
                "entrypoint": case.entrypoint,
                "public_files": [value.to_dict() for value in case.public_files],
                "receipt_path": "receipt.json",
            }
            request_bytes = _atomic_json(subject_root / "request.json", subject_request, MAX_RECEIPT_BYTES)
            request_sha256 = _hash_bytes(request_bytes)
            self._invoke(
                self.config.subject_command,
                subject_root / "request.json",
                cwd=subject_root,
                environment=self.config.subject_environment,
            )
            self._verify_control_copy("suite.json", self.suite_sha256)
            self._verify_control_copy("baseline.json", self.baseline_sha256)
            self._verify_staged_case(case, subject_root, request_sha256)
            try:
                subject = self._subject_receipt(subject_root / "receipt.json")
            except EffectTrialError as exc:
                raise EffectTrialError("subject_receipt_invalid") from exc
            if harness_root.exists():
                raise EffectTrialError("subject_created_harness_workspace")
            harness_root.mkdir()
            harness_request = {
                "schema_version": "1", "candidate_workspace": "../subject", "run_index": run_index,
                "benchmark": self.suite.benchmark.to_dict(),
                "evaluation_profile": self.suite.evaluation_profile.to_dict(),
                "case": case.public_identity(), "harness": case.harness.to_dict(),
                "receipt_path": "receipt.json",
            }
            _atomic_json(harness_root / "request.json", harness_request, MAX_RECEIPT_BYTES)
            self._invoke(
                self.config.harness_command,
                harness_root / "request.json",
                cwd=harness_root,
                environment=self.config.harness_environment,
            )
            self._verify_control_copy("suite.json", self.suite_sha256)
            self._verify_control_copy("baseline.json", self.baseline_sha256)
            self._verify_staged_case(case, subject_root, request_sha256)
            try:
                scored = self._harness_receipt(harness_root / "receipt.json", case)
            except EffectTrialError as exc:
                raise EffectTrialError("harness_receipt_invalid") from exc
            return {
                "schema_version": "1", "case_key": case.key, "run_index": run_index,
                "attempt": f"cases/{case.key}/runs/{run_index:03d}/attempts/{attempt_index:03d}",
                "status": "completed", "ready": True, "elapsed_ms": self._elapsed(started),
                **subject, **scored, "error_code": None,
            }
        except EffectTrialError as exc:
            code = str(exc)
            if code.startswith("frozen "):
                raise
            if code not in {
                "process_timeout", "process_start_failed", "process_result_invalid", "process_nonzero_exit",
                "subject_receipt_invalid", "harness_receipt_invalid", "subject_created_harness_workspace",
            }:
                code = "trial_boundary_failed"
            return self._failed_record(case, run_index, attempt_index, started, code)

    def _store_record(self, case: TrialCase, run_index: int, record: dict[str, Any], state: dict[str, Any]) -> None:
        self._validate_record(record, case, run_index)
        content = _atomic_json(self._record_path(case, run_index), record, MAX_RECEIPT_BYTES)
        state["records"][self._record_key(case, run_index)] = _hash_bytes(content)
        _atomic_json(self._state_path(), state)

    def _case_report(self, case: TrialCase, records: list[dict[str, Any]]) -> dict[str, Any]:
        baseline = next(value for value in self.baseline.cases if value.key == case.key)
        ready = [value for value in records if value["ready"]]
        validity = [float(value["validity_score"]) for value in ready if value["validity_score"] is not None]
        valid = [
            value for value in ready
            if value["extraction_status"] == "completed"
            and value["validity_score"] not in {None, 0.0}
            and value["overall_score"] is not None
        ]
        lunar_best = max((float(value["overall_score"]) for value in valid), default=None)
        historical_best = baseline.best()
        delta = lunar_best - historical_best if lunar_best is not None and historical_best is not None else None
        breakthrough = delta is not None and delta > 0
        model_match = bool(ready) and all(
            value["requested_model"] == self.baseline.model.requested
            and value["effective_model"] == self.baseline.model.effective
            for value in ready
        )
        milestone = breakthrough and len(ready) == self.config.runs_per_case and model_match
        projected_runs = [
            {
                "run_index": value["run_index"], "status": value["status"], "ready": value["ready"],
                "elapsed_ms": value["elapsed_ms"], "requested_model": value["requested_model"],
                "effective_model": value["effective_model"], "model_evidence": value["model_evidence"],
                "interaction_turns": value["interaction_turns"], "usage": value["usage"],
                "extraction_status": value["extraction_status"], "validity_score": value["validity_score"],
                "overall_score": value["overall_score"], "quality_score": value["quality_score"],
                "detail_metrics": value["detail_metrics"], "error_code": value["error_code"],
                "attempt": value["attempt"],
            }
            for value in records
        ]
        return {
            "key": case.key, "revision_id": case.revision_id, "digest": case.digest,
            "harness": case.harness.to_dict(),
            "planned_runs": self.config.runs_per_case, "ready_runs": len(ready),
            "valid_runs": len(valid), "valid_rate": sum(validity) / len(validity) if validity else None,
            "lunar_best": lunar_best, "webagent_historical_best": historical_best,
            "score_delta": delta, "score_breakthrough": breakthrough,
            "model_identity_match": model_match, "milestone_achieved": milestone,
            "runs": projected_runs,
        }

    def _verify_registered_records(self, state: dict[str, Any]) -> None:
        expected = {
            self._record_key(case, run_index)
            for case in self.suite.cases
            for run_index in range(1, self.config.runs_per_case + 1)
        }
        if set(state["records"]) != expected:
            raise EffectTrialError("trial state does not cover every planned logical run")
        for case in self.suite.cases:
            for run_index in range(1, self.config.runs_per_case + 1):
                self._load_record(case, run_index, state)

    def run(self) -> EffectTrialReport:
        if self._started:
            raise EffectTrialError("effect trial runner can only be run once")
        self._started = True
        self._verify_sources()
        state = self._prepare_state()
        case_reports: list[dict[str, Any]] = []
        for case in self.suite.cases:
            records: list[dict[str, Any]] = []
            for run_index in range(1, self.config.runs_per_case + 1):
                record = self._load_record(case, run_index, state)
                if record is None:
                    record = self._execute_run(case, run_index)
                    self._store_record(case, run_index, record, state)
                records.append(record)
            case_reports.append(self._case_report(case, records))
        self._verify_sources()
        self._verify_control_copy("suite.json", self.suite_sha256)
        self._verify_control_copy("baseline.json", self.baseline_sha256)
        self._verify_registered_records(state)
        achieved = [value["key"] for value in case_reports if value["milestone_achieved"]]
        subject_evidence = [
            run["model_evidence"] for case in case_reports for run in case["runs"] if run["ready"]
        ]
        provider_observed = self.baseline.model.evidence == "provider_observed" and bool(subject_evidence) and all(
            value == "provider_observed" for value in subject_evidence
        )
        report_payload = {
            "schema_version": "1", "protocol": "famou-bench-breakthrough-v1", "mode": "normal",
            "suite_sha256": self.suite_sha256, "baseline_sha256": self.baseline_sha256,
            "benchmark": self.suite.benchmark.to_dict(),
            "evaluation_profile": self.suite.evaluation_profile.to_dict(),
            "baseline": {
                "source": self.baseline.source,
                "experiment_id": self.baseline.experiment_id,
                "authority": self.baseline.authority,
                "model": self.baseline.model.to_dict(),
            },
            "config": self.config.safe_dict(), "cases": case_reports,
            "milestone": {"achieved": bool(achieved), "case_keys": achieved},
            "comparability": {
                "kind": "descriptive_same_frozen_harness",
                "model_identity_evidence": "provider_observed" if provider_observed else "not_provider_observed",
                "formal_conclusion_eligibility": "ineligible",
                "baseline_conclusion_eligibility": self.baseline.conclusion_eligibility,
                "limitations": list(_LIMITATIONS),
            },
        }
        _atomic_json(self.workspace / "report.json", report_payload, MAX_MANIFEST_BYTES)
        return EffectTrialReport(report_payload)


__all__ = [
    "EffectTrialConfig", "EffectTrialError", "EffectTrialReport", "EffectTrialRunner",
    "TrialBaseline", "TrialSuite",
]
