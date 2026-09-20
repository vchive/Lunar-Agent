"""Durable registration trust root and one-slot admission for Feature 139.

The committed manifest bytes are the trust root.  Digests supplied by a caller,
or stored only in memory, never authorize a launch.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import campaign
from .case import GOAL, INPUT_BYTES, MODEL

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MANIFEST = HERE / "manifest.json"
REFERENCE = REPO / "specs/134-budgeted-multifile-acceptance/measurement/manifest.json"
HISTORICAL_ANCHOR_COMMIT = "57bd00d06562b2db7ce8df936e5bc6fb0456eca2"
_GENERATED_FIELDS = {
    "registered_utc",
    "registration_base_commit",
    "runtime",
    "product_files",
    "measurement_files",
    "historical_files",
}
_DIGEST_KEYS = {"endpoint_sha256", "chat_endpoint_sha256"}
_SECRET_KEYS = {
    "api_key", "authorization", "credential", "credentials", "password", "secret", "token",
}
_URL_KEYS = {"base_url", "chat_endpoint", "endpoint", "url"}


class RegistrationStoreError(ValueError):
    """The persistent registration or launch preflight is invalid."""


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RegistrationStoreError(f"{label}_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite")),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, RegistrationStoreError):
            raise
        raise RegistrationStoreError(f"{label}_invalid_json") from exc
    if type(value) is not dict:
        raise RegistrationStoreError(f"{label}_invalid_json")
    return value


def _safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise RegistrationStoreError("invalid_inventory_path")
    return path.as_posix()


def _safe_provider_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    metadata = copy.deepcopy(dict(value))
    for key, item in metadata.items():
        normalized = key.lower().replace("-", "_")
        if normalized in _SECRET_KEYS or normalized in _URL_KEYS:
            raise RegistrationStoreError("unsafe_provider_metadata")
        if normalized == "credential_present":
            if type(item) is not bool:
                raise RegistrationStoreError("unsafe_provider_metadata")
        elif normalized in _DIGEST_KEYS:
            if type(item) is not str or len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
                raise RegistrationStoreError("unsafe_provider_metadata")
        elif type(item) not in (str, bool, type(None), int):
            raise RegistrationStoreError("unsafe_provider_metadata")
    return metadata


def runtime_identity() -> dict[str, str]:
    import famou

    python = Path(sys.executable).resolve()
    module = Path(famou.__file__).resolve()
    return {
        "python": str(python),
        "python_sha256": sha256_bytes(python.read_bytes()),
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "famou_module": str(module),
        "famou_module_sha256": sha256_bytes(module.read_bytes()),
    }


def fixed_contract() -> dict[str, Any]:
    """Return every non-temporal launch condition frozen before registration."""
    reference = _strict_json(REFERENCE.read_bytes(), label="reference_manifest")
    provider = _safe_provider_metadata(reference["provider"])
    return {
        **campaign.default_manifest(),
        "task_utf8": GOAL,
        "input_utf8": INPUT_BYTES.decode("utf-8"),
        "provider_safe_metadata": provider,
        "runtime_options": {
            "entrypoint": "solve --evolve --multi-file",
            # Keep the complete native launch intent in the registration.  The
            # worker expands only these four path/model placeholders and
            # rejects any argv drift before loading a provider.
            "launch_argv": [
                "solve", GOAL, "--evolve", "--multi-file",
                "--workspace", "{workspace}", "--home", "{home}",
                "--runtime", "openai-compatible", "--model", "{model}",
                "--agent-loop", "--max-steps", "12",
                "--candidate-generation-max-steps", "12", "--workers", "1",
                "--population-size", "1", "--offspring-per-iteration", "1",
                "--islands", "1", "--max-rounds", "1", "--stagnation-rounds", "3",
                "--seed", "139", "--timeout", "600",
                "--evaluator-preparation-timeout", "900",
                "--evaluator-preparation-wall-timeout", "1860", "--json",
                "--input", "{input}",
            ],
            "runtime": "openai-compatible",
            "model": MODEL,
            "agent_loop": True,
            "max_steps": 12,
            "candidate_generation_max_steps": 12,
            "workers": 1,
            "max_retries": 1,
            "memory": False,
            "session_history": False,
            "allow_exec": False,
            "generated_contract": True,
            "evaluator_invocation": "snapshot",
            "terminal_resume": False,
        },
        "evaluator_profile": {
            "kind": "generated_frozen_bundle",
            "invocation": "snapshot",
            "independent_audit": True,
            "holdout_count": 8,
        },
    }


@dataclass(frozen=True)
class VerifiedRegistration:
    manifest: dict[str, Any]
    manifest_sha256: str
    registration_commit: str


class RegistrationRepository:
    """Filesystem and Git verifier for one concrete registration."""

    def __init__(
        self,
        *,
        repo: Path,
        manifest_path: Path,
        expected_contract: Mapping[str, Any],
        measurement_names: Iterable[str] | Callable[[], Iterable[str]],
        historical_names: Iterable[str] | Callable[[], Iterable[str]],
        prior_manifest_names: Iterable[str] | Callable[[], Iterable[str]] = (),
        provider_probe: Callable[[], Mapping[str, Any]],
        runtime_probe: Callable[[], Mapping[str, Any]] = runtime_identity,
        now: Callable[[], str] | None = None,
        historical_anchor_commit: str | None = None,
    ) -> None:
        self.repo = repo.resolve()
        self.manifest_path = manifest_path
        self.expected_contract = copy.deepcopy(dict(expected_contract))
        self._measurement_names = measurement_names
        self._historical_names = historical_names
        self._prior_manifest_names = prior_manifest_names
        self._provider_probe = provider_probe
        self._runtime_probe = runtime_probe
        self._now = now or (lambda: datetime.now(UTC).isoformat())
        self._historical_anchor_commit = historical_anchor_commit
        try:
            self.manifest_name = manifest_path.relative_to(self.repo).as_posix()
        except ValueError as exc:
            raise RegistrationStoreError("manifest_outside_repository") from exc
        self._validate_contract(self.expected_contract)

    def _git_bytes(self, *args: str) -> bytes:
        try:
            return subprocess.check_output(["git", *args], cwd=self.repo)
        except subprocess.CalledProcessError as exc:
            raise RegistrationStoreError("git_preflight_failed") from exc

    def _git_text(self, *args: str) -> str:
        return self._git_bytes(*args).decode("utf-8").strip()

    @staticmethod
    def _resolve_names(
        source: Iterable[str] | Callable[[], Iterable[str]], *, allow_empty: bool = False,
    ) -> tuple[str, ...]:
        values = source() if callable(source) else source
        names = tuple(sorted({_safe_relative(str(name)) for name in values}))
        if not names and not allow_empty:
            raise RegistrationStoreError("empty_inventory")
        return names

    def _assert_directory_chain(self, directory: Path) -> None:
        try:
            relative = directory.relative_to(self.repo)
        except ValueError as exc:
            raise RegistrationStoreError("path_outside_repository") from exc
        current = self.repo
        for part in relative.parts:
            current /= part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError as exc:
                raise RegistrationStoreError("parent_directory_missing") from exc
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise RegistrationStoreError("parent_directory_symlink_or_invalid")

    def _assert_no_symlink(self, path: Path, *, require_file: bool = True) -> None:
        try:
            relative = path.relative_to(self.repo)
        except ValueError as exc:
            raise RegistrationStoreError("path_outside_repository") from exc
        current = self.repo
        for part in relative.parts:
            current /= part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError as exc:
                raise RegistrationStoreError("registered_file_missing") from exc
            if stat.S_ISLNK(mode):
                raise RegistrationStoreError("registered_symlink_rejected")
        if require_file and not stat.S_ISREG(path.stat().st_mode):
            raise RegistrationStoreError("registered_file_not_regular")

    def _inventory(self, names: Iterable[str]) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for name in names:
            safe_name = _safe_relative(name)
            path = self.repo / safe_name
            self._assert_no_symlink(path)
            raw = path.read_bytes()
            result[safe_name] = {"size": len(raw), "sha256": sha256_bytes(raw)}
        return result

    def _product_names(self) -> tuple[str, ...]:
        commit = self.expected_contract["product_commit"]
        names = tuple(filter(None, self._git_text(
            "ls-tree", "-r", "--name-only", commit, "--", "src", "pyproject.toml",
        ).splitlines()))
        tracked = tuple(filter(None, self._git_text("ls-files", "src", "pyproject.toml").splitlines()))
        if not names or set(names) != set(tracked):
            raise RegistrationStoreError("product_file_set_changed")
        for name in names:
            path = self.repo / name
            self._assert_no_symlink(path)
            if path.read_bytes() != self._git_bytes("show", f"{commit}:{name}"):
                raise RegistrationStoreError("product_bytes_changed")
        return tuple(sorted(names))

    def _validate_contract(self, value: Mapping[str, Any]) -> None:
        contract = copy.deepcopy(dict(value))
        campaign.validate_registration(
            {key: contract[key] for key in campaign.default_manifest()},
            head="fixed", origin="fixed",
        )
        if contract.get("task_utf8") != GOAL or contract.get("input_utf8") != INPUT_BYTES.decode("utf-8"):
            raise RegistrationStoreError("task_or_input_bytes_changed")
        expected_keys = set(campaign.default_manifest()) | {
            "task_utf8", "input_utf8", "provider_safe_metadata", "runtime_options", "evaluator_profile",
        }
        if set(contract) != expected_keys:
            raise RegistrationStoreError("fixed_contract_schema_changed")
        _safe_provider_metadata(contract["provider_safe_metadata"])

    def _prior_values(self) -> list[dict[str, Any]]:
        values = []
        for name in self._resolve_names(self._prior_manifest_names, allow_empty=True):
            path = self.repo / name
            self._assert_no_symlink(path)
            values.append(_strict_json(path.read_bytes(), label="prior_manifest"))
        return values

    def _assert_unique_identity(self) -> None:
        registration_id = self.expected_contract["registration_id"]
        campaign_id = self.expected_contract["campaign_id"]
        campaign_root = self.expected_contract["campaign_root"]
        for prior in self._prior_values():
            if registration_id in {prior.get("registration_id"), prior.get("campaign_id")}:
                raise RegistrationStoreError("duplicate_registration_identity")
            if campaign_id in {prior.get("registration_id"), prior.get("campaign_id")}:
                raise RegistrationStoreError("duplicate_campaign_identity")
            if campaign_root == prior.get("campaign_root"):
                raise RegistrationStoreError("historical_campaign_root_reuse")

    def _require_clean_pushed(self) -> str:
        if self._git_text("status", "--porcelain", "--untracked-files=all"):
            raise RegistrationStoreError("worktree_dirty")
        head = self._git_text("rev-parse", "HEAD")
        try:
            origin = self._git_text("rev-parse", "origin/main")
        except RegistrationStoreError as exc:
            raise RegistrationStoreError("registration_not_pushed") from exc
        if head != origin:
            raise RegistrationStoreError("registration_not_pushed")
        return head

    def _read_manifest(self) -> tuple[bytes, dict[str, Any]]:
        self._assert_no_symlink(self.manifest_path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.manifest_path, flags)
        except OSError as exc:
            raise RegistrationStoreError("manifest_open_failed") from exc
        try:
            raw = b""
            while chunk := os.read(descriptor, 1024 * 1024):
                raw += chunk
        finally:
            os.close(descriptor)
        value = _strict_json(raw, label="manifest")
        if raw != canonical_bytes(value):
            raise RegistrationStoreError("manifest_not_canonical")
        return raw, value

    def _write_exclusive(self, path: Path, value: object) -> None:
        self._assert_directory_chain(path.parent)
        raw = canonical_bytes(value)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise RegistrationStoreError("exclusive_path_already_exists") from exc
        except OSError as exc:
            raise RegistrationStoreError("exclusive_write_failed") from exc
        try:
            offset = 0
            while offset < len(raw):
                offset += os.write(descriptor, raw[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def register(self) -> dict[str, object]:
        """Create one canonical manifest without making a provider request."""
        try:
            self.manifest_path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RegistrationStoreError("registration_already_exists")
        base = self._require_clean_pushed()
        self._assert_unique_identity()
        observed_provider = _safe_provider_metadata(self._provider_probe())
        if observed_provider != self.expected_contract["provider_safe_metadata"]:
            raise RegistrationStoreError("provider_identity_changed")
        payload = {
            **copy.deepcopy(self.expected_contract),
            "registered_utc": self._now(),
            "registration_base_commit": base,
            "runtime": copy.deepcopy(dict(self._runtime_probe())),
            "product_files": self._inventory(self._product_names()),
            "measurement_files": self._inventory(self._resolve_names(self._measurement_names)),
            "historical_files": self._inventory(self._resolve_names(self._historical_names)),
        }
        self._write_exclusive(self.manifest_path, payload)
        return {
            "status": "registered",
            "manifest_sha256": sha256_bytes(canonical_bytes(payload)),
            "model_calls": 0,
        }

    def _verify_inventory(self, manifest: Mapping[str, Any], *, committed: bool) -> None:
        groups = {
            "product_files": self._product_names(),
            "measurement_files": self._resolve_names(self._measurement_names),
            "historical_files": self._resolve_names(self._historical_names),
        }
        for group, names in groups.items():
            expected = manifest[group]
            actual = self._inventory(names)
            if expected != actual:
                raise RegistrationStoreError(f"{group}_changed")
            if committed:
                for name in names:
                    if self._git_bytes("show", f"HEAD:{name}") != (self.repo / name).read_bytes():
                        raise RegistrationStoreError("registered_bytes_not_committed")
        if self._historical_anchor_commit is not None:
            anchor = self._historical_anchor_commit
            anchored = tuple(filter(None, self._git_text(
                "ls-tree", "-r", "--name-only", anchor, "--",
                "specs/131-small-multifile-recheck", "specs/134-budgeted-multifile-acceptance",
            ).splitlines()))
            if set(anchored) != set(groups["historical_files"]):
                raise RegistrationStoreError("historical_file_set_changed")
            for name in anchored:
                if self._git_bytes("show", f"{anchor}:{name}") != (self.repo / name).read_bytes():
                    raise RegistrationStoreError("historical_bytes_changed")

    def _validate_manifest(self, manifest: Mapping[str, Any]) -> None:
        if set(manifest) != set(self.expected_contract) | _GENERATED_FIELDS:
            raise RegistrationStoreError("manifest_schema_changed")
        if any(manifest.get(key) != value for key, value in self.expected_contract.items()):
            raise RegistrationStoreError("fixed_contract_changed")
        self._validate_contract({key: manifest[key] for key in self.expected_contract})
        if (type(manifest["registered_utc"]) is not str or not manifest["registered_utc"]
                or type(manifest["registration_base_commit"]) is not str
                or not manifest["registration_base_commit"]
                or type(manifest["runtime"]) is not dict):
            raise RegistrationStoreError("registration_metadata_invalid")
        if manifest["runtime"] != dict(self._runtime_probe()):
            raise RegistrationStoreError("runtime_identity_changed")

    def verify(self, *, committed: bool = False) -> VerifiedRegistration:
        """Reload and verify registration; committed mode derives trust from Git bytes."""
        raw, manifest = self._read_manifest()
        self._validate_manifest(manifest)
        self._assert_unique_identity()
        self._verify_inventory(manifest, committed=committed)
        if not committed:
            return VerifiedRegistration(manifest, sha256_bytes(raw), "")

        head = self._require_clean_pushed()
        committed_raw = self._git_bytes("show", f"HEAD:{self.manifest_name}")
        if committed_raw != raw:
            raise RegistrationStoreError("manifest_bytes_not_committed")
        committed_manifest = _strict_json(committed_raw, label="committed_manifest")
        if committed_raw != canonical_bytes(committed_manifest):
            raise RegistrationStoreError("committed_manifest_not_canonical")
        base = manifest["registration_base_commit"]
        if type(base) is not str or not base or self._git_text("rev-parse", "HEAD^") != base:
            raise RegistrationStoreError("registration_base_commit_changed")
        changed = set(self._git_text("diff", "--name-only", base, head).splitlines())
        if changed != {self.manifest_name}:
            raise RegistrationStoreError("registration_commit_scope_changed")
        return VerifiedRegistration(manifest, sha256_bytes(committed_raw), head)

    def _campaign_path(self, manifest: Mapping[str, Any]) -> Path:
        root_name = _safe_relative(str(manifest["campaign_root"]))
        if tuple(PurePosixPath(root_name).parts[:1]) != (".lunar",):
            raise RegistrationStoreError("campaign_root_invalid")
        return self.repo / root_name

    def verify_launch(self) -> VerifiedRegistration:
        verified = self.verify(committed=True)
        if _safe_provider_metadata(self._provider_probe()) != verified.manifest["provider_safe_metadata"]:
            raise RegistrationStoreError("provider_identity_changed")
        root = self._campaign_path(verified.manifest)
        try:
            root.lstat()
        except FileNotFoundError:
            return verified
        raise RegistrationStoreError("campaign_root_already_used")

    def admit_one_slot(self) -> dict[str, Any]:
        """Atomically consume the only root and attempt after a fresh Git verification."""
        verified = self.verify_launch()
        manifest = verified.manifest
        root = self._campaign_path(manifest)
        parent = root.parent
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            os.mkdir(parent, 0o700)
            repo_descriptor = os.open(self.repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(repo_descriptor)
            finally:
                os.close(repo_descriptor)
        else:
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise RegistrationStoreError("campaign_parent_invalid")
        try:
            os.mkdir(root, 0o700)
        except FileExistsError as exc:
            raise RegistrationStoreError("campaign_root_already_used") from exc
        parent_descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)

        marker = {
            "schema_version": "1",
            "registration_id": manifest["registration_id"],
            "campaign_id": manifest["campaign_id"],
            "attempt_id": manifest["attempt_id"],
            "registration_commit": verified.registration_commit,
            "manifest_sha256": verified.manifest_sha256,
            "admitted_utc": self._now(),
        }
        self._write_exclusive(root / "admission.json", marker)
        slot = root / str(manifest["attempt_id"])
        try:
            os.mkdir(slot, 0o700)
        except FileExistsError as exc:
            raise RegistrationStoreError("attempt_slot_already_used") from exc
        root_descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
        self._write_exclusive(slot / "admission.json", marker)
        return marker


def _tracked_feature_names(repo: Path) -> tuple[str, ...]:
    output = subprocess.check_output(
        [
            "git", "ls-files", "specs/139-real-multifile-closure",
            "tests/measurement139_*.py", "tests/test_measurement139_*.py",
            "specs/113-real-multifile-acceptance/measurement/runtime_guard.py",
            "tests/test_measurement134_case.py",
        ],
        cwd=repo,
        text=True,
    )
    return tuple(
        name for name in output.splitlines()
        if name and name != "specs/139-real-multifile-closure/measurement/manifest.json"
        and not name.startswith("specs/139-real-multifile-closure/postrun/")
    )


def _tracked_historical_names(repo: Path) -> tuple[str, ...]:
    output = subprocess.check_output(
        [
            "git", "ls-files", "specs/131-small-multifile-recheck",
            "specs/134-budgeted-multifile-acceptance",
        ],
        cwd=repo,
        text=True,
    )
    return tuple(filter(None, output.splitlines()))


def _prior_manifest_names(repo: Path) -> tuple[str, ...]:
    output = subprocess.check_output(
        ["git", "ls-files", "specs/*/measurement/manifest.json"],
        cwd=repo,
        text=True,
    )
    return tuple(name for name in output.splitlines() if name and repo / name != MANIFEST)


def default_repository() -> RegistrationRepository:
    """Build the production repository adapter without contacting the provider."""
    from .observation import load_provider

    contract = fixed_contract()

    def provider_probe() -> Mapping[str, Any]:
        provider = load_provider(requested_model=MODEL, expected=contract["provider_safe_metadata"])
        return provider.safe_metadata(MODEL)

    return RegistrationRepository(
        repo=REPO,
        manifest_path=MANIFEST,
        expected_contract=contract,
        measurement_names=lambda: _tracked_feature_names(REPO),
        historical_names=lambda: _tracked_historical_names(REPO),
        prior_manifest_names=lambda: _prior_manifest_names(REPO),
        provider_probe=provider_probe,
        historical_anchor_commit=HISTORICAL_ANCHOR_COMMIT,
    )
