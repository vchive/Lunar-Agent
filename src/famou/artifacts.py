"""Run-scoped artifact handling with path confinement."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .store import Store


class ArtifactError(ValueError):
    """An artifact path is invalid or escapes its run workspace."""


class ArtifactStore:
    def __init__(self, root: str | Path, store: Store, run_id: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store
        self.run_id = run_id
        self.root.mkdir(parents=True, exist_ok=True)

    def safe_path(self, relative_path: str | Path) -> Path:
        candidate = (self.root / Path(relative_path)).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactError(f"artifact path escapes run workspace: {relative_path}") from exc
        return candidate

    def write_text(self, relative_path: str, content: str, task_id: str, kind: str = "result") -> Path:
        path = self.safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.record(path, task_id, kind)
        return path

    def record(self, path: str | Path, task_id: str, kind: str = "result") -> str:
        path = Path(path).resolve(strict=False)
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactError(f"artifact is outside run workspace: {path}") from exc
        if not path.is_file():
            raise ArtifactError(f"artifact is not a file: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return self.store.add_artifact(
            self.run_id,
            task_id,
            str(relative),
            digest,
            path.stat().st_size,
            kind,
        )
