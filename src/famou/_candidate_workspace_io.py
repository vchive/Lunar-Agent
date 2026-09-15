"""Descriptor-relative writes and bounded cleanup for private candidate workspaces."""
from __future__ import annotations

import os
import secrets
import stat
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from .candidate_workspace_plan import CandidateWorkspaceError

_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def fail(code: str) -> None:
    raise CandidateWorkspaceError(code)


def identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


class DirectoryChain:
    """Hold and recheck each absolute directory name without following links."""

    def __init__(self, path: Path, code: str) -> None:
        self.fds: list[int] = []
        self.links: list[tuple[int, str, int]] = []
        self.code = code
        try:
            self.fds.append(os.open(path.anchor, _FLAGS))
            for name in path.parts[1:]:
                parent = self.fds[-1]
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    fail(code)
                child = os.open(name, _FLAGS, dir_fd=parent)
                self.fds.append(child)
                self.links.append((parent, name, child))
                if identity(before) != identity(os.fstat(child)):
                    fail(code)
            self.check()
        except Exception:
            self.close()
            raise

    @property
    def fd(self) -> int:
        return self.fds[-1]

    def check(self) -> None:
        for parent, name, child in reversed(self.links):
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or identity(info) != identity(os.fstat(child)):
                fail(self.code)

    def close(self) -> None:
        for descriptor in reversed(self.fds):
            os.close(descriptor)
        self.fds.clear()


class PrivateTree:
    """A new leaf owned through its open directory descriptor, never a caller-selected path."""

    def __init__(self, parent: DirectoryChain) -> None:
        self.parent = parent
        self.fd = -1
        self.directories: dict[tuple[str, ...], tuple[int, int]] = {}
        self.files: dict[tuple[str, ...], tuple[int, int]] = {}
        for _ in range(8):
            self.name = '.candidate-workspace-' + secrets.token_hex(12)
            try:
                os.mkdir(self.name, 0o700, dir_fd=parent.fd)
                break
            except FileExistsError:
                continue
        else:
            fail('destination_conflict')
        try:
            before = os.stat(self.name, dir_fd=parent.fd, follow_symlinks=False)
            self.fd = os.open(self.name, _FLAGS, dir_fd=parent.fd)
            if identity(before) != identity(os.fstat(self.fd)):
                fail('destination_changed')
            os.fchmod(self.fd, 0o700)
            self.directories[()] = identity(os.fstat(self.fd))
            self.check_root()
        except BaseException:
            # If opening the new name was interrupted, do not guess which tree is ours.
            if self.fd >= 0:
                os.close(self.fd)
            fail('cleanup_failed')

    def check_root(self) -> None:
        self.parent.check()
        info = os.stat(self.name, dir_fd=self.parent.fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or identity(info) != self.directories[()]:
            fail('destination_changed')

    @contextmanager
    def directory(self, parts: tuple[str, ...], *, create: bool = False):
        opened: list[int] = []
        links: list[tuple[int, str, int]] = []
        descriptor = self.fd
        try:
            for depth, name in enumerate(parts, 1):
                key = parts[:depth]
                if create and key not in self.directories:
                    os.mkdir(name, 0o700, dir_fd=descriptor)
                    self.directories[key] = identity(os.stat(name, dir_fd=descriptor, follow_symlinks=False))
                child = os.open(name, _FLAGS, dir_fd=descriptor)
                opened.append(child)
                links.append((descriptor, name, child))
                if identity(os.fstat(child)) != self.directories[key]:
                    fail('destination_changed')
                if create:
                    os.fchmod(child, 0o700)
                descriptor = child
            yield descriptor
            for parent, name, child in reversed(links):
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode) or identity(info) != identity(os.fstat(child)):
                    fail('destination_changed')
        finally:
            for child in reversed(opened):
                os.close(child)

    def write(self, relative: str, content: bytes) -> None:
        parts = tuple(relative.split('/'))
        with self.directory(parts[:-1], create=True) as parent:
            descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            try:
                self.files[parts] = identity(os.fstat(descriptor))
                os.fchmod(descriptor, 0o600)
                view = memoryview(content)
                while view:
                    count = os.write(descriptor, view)
                    if count <= 0:
                        fail('destination_write_failed')
                    view = view[count:]
                os.fsync(descriptor)
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or identity(info) != self.files[parts]
                        or info.st_nlink != 1 or info.st_size != len(content)):
                    fail('destination_changed')
            finally:
                os.close(descriptor)

    def sync_and_check(self) -> None:
        # Enumerate only our destination tree, stopping as soon as one extra entry appears.
        for parts in sorted(self.directories, key=len, reverse=True):
            with self.directory(parts) as descriptor:
                expected = {key[-1] for key in (*self.directories, *self.files)
                            if key and key[:-1] == parts}
                seen: set[str] = set()
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        name = unicodedata.normalize('NFC', entry.name)
                        if name not in expected or name in seen:
                            fail('destination_changed')
                        seen.add(name)
                        key = (*parts, name)
                        info = entry.stat(follow_symlinks=False)
                        wanted = self.files.get(key, self.directories.get(key))
                        mode = 0o600 if key in self.files else 0o700
                        regular = stat.S_ISREG(info.st_mode) if key in self.files else stat.S_ISDIR(info.st_mode)
                        if (identity(info) != wanted or not regular or stat.S_IMODE(info.st_mode) != mode
                                or (key in self.files and info.st_nlink != 1)):
                            fail('destination_changed')
                if seen != expected or stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
                    fail('destination_changed')
                os.fsync(descriptor)
        os.fsync(self.parent.fd)
        self.check_root()

    def cleanup(self) -> None:
        # Remove only recorded names with matching identities. A replacement tree is retained.
        for parts, wanted in reversed(list(self.files.items())):
            with self.directory(parts[:-1]) as descriptor:
                info = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
                if identity(info) != wanted or not stat.S_ISREG(info.st_mode):
                    fail('cleanup_failed')
                os.unlink(parts[-1], dir_fd=descriptor)
        for parts in sorted(self.directories, key=len, reverse=True):
            if not parts:
                continue
            with self.directory(parts[:-1]) as descriptor:
                info = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
                if identity(info) != self.directories[parts] or not stat.S_ISDIR(info.st_mode):
                    fail('cleanup_failed')
                os.rmdir(parts[-1], dir_fd=descriptor)
        info = os.stat(self.name, dir_fd=self.parent.fd, follow_symlinks=False)
        if identity(info) != self.directories[()] or not stat.S_ISDIR(info.st_mode):
            fail('cleanup_failed')
        os.rmdir(self.name, dir_fd=self.parent.fd)
        os.fsync(self.parent.fd)

    def close(self) -> None:
        os.close(self.fd)
