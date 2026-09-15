"""Private read-only file boundary shared by static benchmark validators."""
from __future__ import annotations

import os
import stat
from pathlib import Path


class BenchmarkFileError(ValueError):
    """Internal reason; public validators map this to their own fixed codes."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> None:
    raise BenchmarkFileError(reason)


def absolute_path(value: object) -> Path:
    try:
        path = Path(value).expanduser().absolute()
        # Do not resolve or normalize away symlinks or parent traversal before opening.
        if ("\x00" in path.as_posix() or ".." in path.parts
                or len(path.as_posix().encode("utf-8")) > 4096 or len(path.parts) > 128):
            _fail("unsafe")
        return path
    except (OSError, TypeError, ValueError, RuntimeError):
        _fail("unsafe")


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_regular_file(path: Path, maximum: int, *, exact_size: bool = False) -> bytes:
    """Read bounded bytes without following links, then recheck the opened names."""
    invalid = "unsafe"
    missing = "missing"
    changed = "changed"
    large = "too_large"
    descriptors: list[int] = []
    directories: list[tuple[int, str, int]] = []
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    reading_started = False
    try:
        parent = os.open(path.anchor, flags | os.O_DIRECTORY)
        descriptors.append(parent)
        for name in path.parts[1:-1]:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                _fail(invalid)
            child = os.open(name, flags | os.O_DIRECTORY, dir_fd=parent)
            descriptors.append(child)
            opened = os.fstat(child)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                _fail(changed)
            directories.append((parent, name, child))
            parent = child

        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            _fail(invalid)
        if before.st_size > maximum or (exact_size and before.st_size != maximum):
            _fail(large)
        descriptor = os.open(path.name, flags, dir_fd=parent)
        descriptors.append(descriptor)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _file_identity(before) != _file_identity(opened):
            _fail(changed)

        reading_started = True
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > maximum:
            _fail(large)
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(named.st_mode) or _file_identity(before) != _file_identity(after)
                or _file_identity(after) != _file_identity(named) or after.st_size != len(content)):
            _fail(changed)
        for ancestor, name, child in reversed(directories):
            named = os.stat(name, dir_fd=ancestor, follow_symlinks=False)
            opened = os.fstat(child)
            if (not stat.S_ISDIR(named.st_mode)
                    or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)):
                _fail(changed)
        return content
    except FileNotFoundError:
        _fail(changed if reading_started else missing)
    except OSError:
        _fail(changed if reading_started else invalid)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
