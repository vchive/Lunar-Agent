"""Read-only validation for a frozen Famou-Bench effect trial.

The preflight command checks every input that the normal effect trial will use, including the
exact extractor interpreter and its declared dependencies.  It deliberately never invokes the
subject or evaluator commands and emits only content identities, hashes, and environment names.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .effect_trial import (
    MAX_MANIFEST_BYTES,
    EffectTrialConfig,
    EffectTrialError,
    EffectTrialRunner,
    _hash_command,
)

MAX_PROBE_OUTPUT_BYTES = 64 * 1024
MAX_PROBE_TIMEOUT_SECONDS = 30.0
MAX_DEPENDENCIES = 128
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DIST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_VERSION = re.compile(r"^[^\x00\r\n]{1,128}$")


class EffectPreflightError(ValueError):
    """A frozen effect trial cannot pass its read-only preflight."""


@dataclass(frozen=True)
class EffectPreflightReport:
    """Credential-safe result of a completed preflight validation."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))


class EffectPreflightRunner:
    """Reusable wrapper around :func:`run_effect_preflight`."""

    def __init__(self, suite_path: str | Path, baseline_path: str | Path, **kwargs: Any) -> None:
        self.suite_path = suite_path
        self.baseline_path = baseline_path
        self.kwargs = dict(kwargs)

    def run(self) -> EffectPreflightReport:
        return EffectPreflightReport(
            run_effect_preflight(self.suite_path, self.baseline_path, **self.kwargs)
        )


def _canonical_bytes(payload: object) -> bytes:
    try:
        value = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise EffectPreflightError("preflight report is not serializable") from exc
    return (value + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise EffectPreflightError("could not read the harness interpreter") from exc
    return digest.hexdigest()


def _interpreter_path(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute() or raw.is_symlink() or not raw.is_file():
        raise EffectPreflightError("harness Python must be an absolute regular non-symlink file")
    try:
        info = raw.stat()
    except OSError as exc:
        raise EffectPreflightError("could not stat harness Python") from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(raw, os.X_OK):
        raise EffectPreflightError("harness Python must be executable")
    return raw.resolve()


def _dependency_list(values: Sequence[str], kind: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise EffectPreflightError(f"harness {kind} declarations must be a sequence")
    if len(values) > MAX_DEPENDENCIES:
        raise EffectPreflightError("harness dependency declarations exceed their bound")
    output: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise EffectPreflightError(f"harness {kind} declaration is invalid")
        if kind == "import":
            if not _MODULE.fullmatch(value):
                raise EffectPreflightError(f"harness import is not a module name: {value}")
        elif not _DIST.fullmatch(value):
            raise EffectPreflightError(f"harness package is not a distribution name: {value}")
        if value in output:
            raise EffectPreflightError(f"harness {kind} declarations must be unique")
        output.append(value)
    return tuple(output)


def _package_declarations(values: Sequence[str]) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise EffectPreflightError("harness package declarations must be a sequence")
    if len(values) > MAX_DEPENDENCIES:
        raise EffectPreflightError("harness dependency declarations exceed their bound")
    declarations = tuple(values)
    parsed: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for declaration in declarations:
        if not isinstance(declaration, str) or not declaration or "\x00" in declaration:
            raise EffectPreflightError("harness package declaration is invalid")
        if "==" in declaration:
            name, expected = declaration.split("==", 1)
            if not _DIST.fullmatch(name) or not _VERSION.fullmatch(expected):
                raise EffectPreflightError("harness package version declaration is invalid")
            item = (name, expected)
        else:
            if not _DIST.fullmatch(declaration):
                raise EffectPreflightError(f"harness package is not a distribution name: {declaration}")
            item = (declaration, None)
        if item[0] in seen:
            raise EffectPreflightError("harness package declarations must be unique")
        seen.add(item[0])
        parsed.append(item)
    return tuple(parsed)


def _bound_harness_python(command: Sequence[str], interpreter: Path) -> None:
    bindings: list[str] = []
    for index, value in enumerate(command):
        if value == "--python":
            if index + 1 >= len(command):
                raise EffectPreflightError("harness command must contain exactly one --python PATH")
            bindings.append(command[index + 1])
        elif value.startswith("--python="):
            bindings.append(value.split("=", 1)[1])
    if len(bindings) != 1 or not bindings[0]:
        raise EffectPreflightError("harness command must contain exactly one --python PATH")
    supplied = Path(bindings[0]).expanduser()
    if not supplied.is_absolute() or supplied.is_symlink():
        raise EffectPreflightError("harness command --python must be an absolute non-symlink path")
    try:
        resolved = supplied.resolve(strict=True)
    except OSError as exc:
        raise EffectPreflightError("harness command --python path is missing") from exc
    if resolved != interpreter:
        raise EffectPreflightError("harness command --python does not match --harness-python")


def _probe_interpreter(
    interpreter: Path,
    imports: tuple[str, ...],
    packages: tuple[tuple[str, str | None], ...],
) -> dict[str, Any]:
    request = {
        "imports": list(imports),
        "packages": [{"name": name, "expected": expected} for name, expected in packages],
    }
    # Resolve each path component without importing its parent. Using the basename with an
    # explicit search path also avoids namespace specs looking up absent parents in sys.modules.
    # Packages that only expose children by executing __init__.py are intentionally unresolved.
    script = (
        "import importlib.metadata as m, importlib.machinery as f, json, sys\n"
        "r=json.loads(sys.argv[1]); out={'imports':{},'packages':{}}\n"
        "def available(name):\n"
        " parts=name.split('.'); locations=None\n"
        " for index, part in enumerate(parts):\n"
        "  fullname='.'.join(parts[:index+1])\n"
        "  spec=f.BuiltinImporter.find_spec(fullname) or f.FrozenImporter.find_spec(fullname)\n"
        "  if spec is None: spec=f.PathFinder.find_spec(part, locations)\n"
        "  if spec is None: return False\n"
        "  if index+1 < len(parts):\n"
        "   if spec.submodule_search_locations is None: return False\n"
        "   locations=tuple(spec.submodule_search_locations)\n"
        " return True\n"
        "for n in r['imports']:\n"
        " try: out['imports'][n]=available(n)\n"
        " except Exception: out['imports'][n]=False\n"
        "for p in r['packages']:\n"
        " n=p['name']\n"
        " try: out['packages'][n]=m.version(n)\n"
        " except Exception: out['packages'][n]=None\n"
        "out['version']='.'.join(str(v) for v in sys.version_info[:3])\n"
        "print(json.dumps(out,separators=(',',':'),sort_keys=True))"
    )
    environment = {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        result = subprocess.run(
            [str(interpreter), "-I", "-B", "-c", script, json.dumps(request, separators=(",", ":"))],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=environment,
            timeout=MAX_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EffectPreflightError("harness Python dependency probe timed out") from exc
    except OSError as exc:
        raise EffectPreflightError("could not start harness Python dependency probe") from exc
    if len(result.stdout) > MAX_PROBE_OUTPUT_BYTES or len(result.stderr) > MAX_PROBE_OUTPUT_BYTES:
        raise EffectPreflightError("harness Python dependency probe output exceeds its bound")
    if result.returncode != 0:
        raise EffectPreflightError("harness Python dependency probe failed")
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EffectPreflightError("harness Python dependency probe returned invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"imports", "packages", "version"}:
        raise EffectPreflightError("harness Python dependency probe returned an invalid shape")
    if not isinstance(payload["version"], str) or not _VERSION.fullmatch(payload["version"]):
        raise EffectPreflightError("harness Python dependency probe returned an invalid version")
    observed_imports = payload["imports"]
    if not isinstance(observed_imports, dict) or set(observed_imports) != set(imports):
        raise EffectPreflightError("harness Python dependency probe returned invalid import observations")
    if any(not isinstance(name, str) or not _MODULE.fullmatch(name) or not isinstance(found, bool)
           for name, found in observed_imports.items()):
        raise EffectPreflightError("harness Python dependency probe returned invalid import observations")
    observed_packages = payload["packages"]
    expected_package_names = {name for name, _ in packages}
    if not isinstance(observed_packages, dict) or set(observed_packages) != expected_package_names:
        raise EffectPreflightError("harness Python dependency probe returned invalid package observations")
    if any(
        not isinstance(name, str)
        or not _DIST.fullmatch(name)
        or (version is not None and (not isinstance(version, str) or not _VERSION.fullmatch(version)))
        for name, version in observed_packages.items()
    ):
        raise EffectPreflightError("harness Python dependency probe returned invalid package observations")
    return payload


def _atomic_report(path: Path, payload: Mapping[str, Any]) -> None:
    content = _canonical_bytes(payload)
    if len(content) > MAX_MANIFEST_BYTES:
        raise EffectPreflightError("preflight report exceeds its bounded size")
    path = path.expanduser().absolute()
    if path.is_symlink() or path.exists():
        raise EffectPreflightError("preflight output must be a new regular file")
    parent = path.parent
    while parent != parent.parent:
        if parent.is_symlink():
            raise EffectPreflightError("preflight output parent must not contain a symlink")
        parent = parent.parent
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link publishes complete bytes atomically and fails if any destination appeared
        # after the initial check. Unlike replace(), it cannot overwrite another writer's report.
        os.link(temporary, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise EffectPreflightError("preflight output must be a new regular file") from exc
    except OSError as exc:
        raise EffectPreflightError("could not write preflight report") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_effect_preflight(
    suite_path: str | Path,
    baseline_path: str | Path,
    *,
    case_sources: Mapping[str, str | Path],
    subject_command: Sequence[str],
    harness_command: Sequence[str],
    requested_model: str,
    harness_python: str | Path,
    harness_imports: Sequence[str] = (),
    harness_packages: Sequence[str] = (),
    subject_environment: Mapping[str, str] | None = None,
    harness_environment: Mapping[str, str] | None = None,
    model_profile_sha256: str | None = None,
    subject_model_profile_path: str | Path | None = None,
    timeout_seconds: float = 3600.0,
    runs_per_case: int = 1,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a trial and return a credential/path-safe report without running it."""
    interpreter = _interpreter_path(harness_python)
    imports = _dependency_list(harness_imports, "import")
    packages = _package_declarations(harness_packages)
    normalized_harness = tuple(harness_command)
    _bound_harness_python(normalized_harness, interpreter)
    try:
        config = EffectTrialConfig(
            runs_per_case=runs_per_case,
            timeout_seconds=timeout_seconds,
            requested_model=requested_model,
            subject_command=tuple(subject_command),
            harness_command=normalized_harness,
            subject_environment=dict(subject_environment or {}),
            harness_environment=dict(harness_environment or {}),
            model_profile_sha256=model_profile_sha256,
            subject_model_profile_path=(
                Path(subject_model_profile_path).expanduser()
                if subject_model_profile_path is not None
                else None
            ),
        )
        for label, command in (("subject", config.subject_command), ("harness", config.harness_command)):
            if not os.access(command[0], os.X_OK):
                raise EffectPreflightError(f"{label} command file must be executable")
        with tempfile.TemporaryDirectory(prefix="famou-effect-preflight-") as temporary:
            runner = EffectTrialRunner(
                suite_path,
                baseline_path,
                Path(temporary),
                case_sources=case_sources,
                config=config,
            )
            probe = _probe_interpreter(interpreter, imports, packages)
    except EffectTrialError as exc:
        raise EffectPreflightError(str(exc)) from exc
    missing_imports = [name for name, found in probe["imports"].items() if found is not True]
    if missing_imports:
        raise EffectPreflightError(
            "harness Python is missing declared imports: " + ", ".join(sorted(missing_imports))
        )
    missing_packages = [name for name, version in probe["packages"].items() if version is None]
    if missing_packages:
        raise EffectPreflightError(
            "harness Python is missing declared packages: " + ", ".join(sorted(missing_packages))
        )
    mismatched_packages = [
        name
        for name, expected in packages
        if expected is not None and probe["packages"].get(name) != expected
    ]
    if mismatched_packages:
        raise EffectPreflightError(
            "harness package versions do not match: " + ", ".join(sorted(mismatched_packages))
        )
    report: dict[str, Any] = {
        "schema_version": "1",
        "protocol": "famou-bench-effect-preflight-v1",
        "status": "ready",
        "suite_sha256": runner.suite_sha256,
        "baseline_sha256": runner.baseline_sha256,
        "benchmark": runner.suite.benchmark.to_dict(),
        "evaluation_profile": runner.suite.evaluation_profile.to_dict(),
        "baseline": {
            "source": runner.baseline.source,
            "experiment_id": runner.baseline.experiment_id,
            "authority": runner.baseline.authority,
            "conclusion_eligibility": runner.baseline.conclusion_eligibility,
            "provenance": (
                runner.baseline.provenance.to_dict()
                if runner.baseline.provenance is not None
                else None
            ),
            "model": runner.baseline.model.to_dict(),
        },
        "cases": [
            {
                **case.public_identity(),
                "entrypoint": case.entrypoint,
                "public_files": [file.to_dict() for file in case.public_files],
                "harness": case.harness.to_dict(),
            }
            for case in runner.suite.cases
        ],
        "subject": {
            "requested_model": config.requested_model,
            "model_profile_sha256": config.model_profile_sha256,
            "command_sha256": _hash_command(config.subject_command),
            "environment_names": sorted(config.subject_environment),
        },
        "harness": {
            "command_sha256": _hash_command(config.harness_command),
            "environment_names": sorted(config.harness_environment),
            "python_sha256": _sha256(interpreter),
            "python_version": probe["version"],
            "imports": probe["imports"],
            "packages": probe["packages"],
        },
        "config": {
            "runs_per_case": config.runs_per_case,
            "timeout_seconds": float(config.timeout_seconds),
        },
    }
    # Verify that the report itself cannot accidentally include a private path or credential.
    content = _canonical_bytes(report)
    if output is not None:
        _atomic_report(Path(output), report)
    del content
    return report


__all__ = [
    "EffectPreflightError",
    "EffectPreflightReport",
    "EffectPreflightRunner",
    "run_effect_preflight",
]
