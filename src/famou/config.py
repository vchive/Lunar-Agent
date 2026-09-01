"""Configuration that is explicit and independent from machine-wide Agent runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    home: Path
    max_retries: int = 2
    runtime_timeout: float = 900.0

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        if self.runtime_timeout <= 0:
            raise ValueError("runtime_timeout must be positive")

    @property
    def database(self) -> Path:
        return self.home / "state.db"

    @property
    def runs(self) -> Path:
        return self.home / "runs"

    def workspace_for(self, run_id: str) -> Path:
        return self.runs / run_id

    def ensure(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, home: str | Path | None = None) -> Config:
        configured_home = home if home is not None else os.environ.get("FAMOU_HOME", ".famou")
        max_retries = int(os.environ.get("FAMOU_MAX_RETRIES", "2"))
        timeout = float(os.environ.get("FAMOU_RUNTIME_TIMEOUT", "900"))
        return cls(Path(configured_home).expanduser().resolve(), max_retries, timeout)
