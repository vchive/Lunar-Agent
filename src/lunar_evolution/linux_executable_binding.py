"""Bind an attested Linux executable to sealed bytes before process creation."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .producer_launcher import MAX_OUTPUT_BYTES

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl module.
    fcntl = None

_CHUNK_SIZE = 64 * 1024
_REQUIRED_SEALS = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")


class LinuxExecutableBindingError(ValueError):
    """Fixed-code failure before an executable is handed to the kernel."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LinuxSealedExecutable:
    fd: int
    sha256: str
    size: int
    binding: str = "linux-sealed-memfd"

    @property
    def executable(self) -> str:
        return f"/proc/self/fd/{self.fd}"

    @property
    def pass_fd(self) -> int:
        return self.fd


def _source_identity(info: os.stat_result, sha256: str) -> dict[str, int | str]:
    return {
        "sha256": sha256,
        "size": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _same_source(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns,
    ) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )


@contextmanager
def sealed_linux_executable(
    source: str | Path,
    expected_identity: Mapping[str, object],
    *,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[LinuxSealedExecutable]:
    """Yield a sealed memfd that remains open through ``Popen``.

    The caller must pass ``binding.executable`` as ``Popen(executable=...)`` and include
    ``binding.pass_fd`` in ``pass_fds``. Keeping that descriptor across exec also lets
    a shebang interpreter reopen the exact sealed script through ``/proc/self/fd``.
    """
    required = tuple(getattr(fcntl, name, None) for name in _REQUIRED_SEALS)
    if (
        not sys.platform.startswith("linux")
        or not callable(getattr(os, "memfd_create", None))
        or not hasattr(os, "MFD_ALLOW_SEALING")
        or not hasattr(os, "MFD_CLOEXEC")
        or not hasattr(fcntl, "F_ADD_SEALS")
        or not hasattr(fcntl, "F_GET_SEALS")
        or any(value is None for value in required)
        or not Path("/proc/self/fd").is_dir()
    ):
        raise LinuxExecutableBindingError("linux_execution_binding_unsupported")
    source_fd = -1
    sealed_fd = -1
    try:
        if monotonic() >= deadline:
            raise LinuxExecutableBindingError("linux_execution_wall_timeout")
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > MAX_OUTPUT_BYTES
            or not before.st_mode & 0o111
            or before.st_mode & (stat.S_ISUID | stat.S_ISGID)
        ):
            raise LinuxExecutableBindingError("linux_execution_source_invalid")
        metadata = _source_identity(before, str(expected_identity.get("sha256", "")))
        if metadata != dict(expected_identity):
            raise LinuxExecutableBindingError("linux_execution_source_changed")

        sealed_fd = os.memfd_create(
            "lunar-producer-executable", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC,
        )
        os.fchmod(sealed_fd, stat.S_IMODE(before.st_mode))
        digest = hashlib.sha256()
        copied = 0
        while copied <= MAX_OUTPUT_BYTES:
            if monotonic() >= deadline:
                raise LinuxExecutableBindingError("linux_execution_wall_timeout")
            chunk = os.read(source_fd, min(_CHUNK_SIZE, MAX_OUTPUT_BYTES + 1 - copied))
            if not chunk:
                break
            copied += len(chunk)
            if copied > before.st_size or copied > MAX_OUTPUT_BYTES:
                raise LinuxExecutableBindingError("linux_execution_source_changed")
            digest.update(chunk)
            offset = 0
            while offset < len(chunk):
                if monotonic() >= deadline:
                    raise LinuxExecutableBindingError("linux_execution_wall_timeout")
                written = os.write(sealed_fd, chunk[offset:])
                if written <= 0:
                    raise LinuxExecutableBindingError("linux_execution_binding_unknown")
                offset += written
        after = os.fstat(source_fd)
        expected_digest = expected_identity.get("sha256")
        if (
            copied != before.st_size
            or not _same_source(before, after)
            or digest.hexdigest() != expected_digest
        ):
            raise LinuxExecutableBindingError("linux_execution_source_changed")
        os.fsync(sealed_fd)
        seals = 0
        for value in required:
            assert isinstance(value, int)
            seals |= value
        fcntl.fcntl(sealed_fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(sealed_fd, fcntl.F_GET_SEALS) & seals != seals:
            raise LinuxExecutableBindingError("linux_execution_binding_unknown")
        if os.fstat(sealed_fd).st_size != copied:
            raise LinuxExecutableBindingError("linux_execution_binding_unknown")
        os.lseek(sealed_fd, 0, os.SEEK_SET)
    except LinuxExecutableBindingError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise LinuxExecutableBindingError("linux_execution_binding_unknown") from exc
    else:
        yield LinuxSealedExecutable(sealed_fd, digest.hexdigest(), copied)
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if sealed_fd >= 0:
            os.close(sealed_fd)
