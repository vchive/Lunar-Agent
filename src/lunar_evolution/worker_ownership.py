"""Local service liveness locks, scoped to one Store and a random execution owner."""

from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path


class WorkerOwnerLock:
    def __init__(self, fd: int) -> None:
        self.fd: int | None = fd

    @classmethod
    def acquire(cls, database: Path, owner: str, *, create: bool = False) -> WorkerOwnerLock | None:
        if re.fullmatch(r"worker-owner-[0-9a-f]{32}", owner) is None:
            raise ValueError("invalid worker execution owner")
        directory = database.parent / (database.name + ".worker-owners")
        if create:
            directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("worker owner directory is unavailable")
        path = directory / (owner + ".lock")
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags | (os.O_CREAT if create else 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("invalid worker owner lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return None
            named = path.lstat()
            if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
                raise ValueError("worker owner lock changed")
            return cls(fd)
        except BaseException:
            os.close(fd)
            raise

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
