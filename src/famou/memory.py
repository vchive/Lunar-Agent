"""Persistent, local-first memory for Hermes-inspired agent sessions.

The memory layer is deliberately small and deterministic.  It stores short user/agent notes in
the same SQLite database as the run ledger and performs bounded lexical retrieval.  There is no
embedding service, vector database, or dependency on a machine-wide Hermes installation.  A future
adapter can replace retrieval without changing the controller or tool contracts.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS memories_scope_idx ON memories(scope, updated_at);
"""


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    scope: str
    kind: str
    content: str
    tags: tuple[str, ...]
    source: str | None
    created_at: str
    updated_at: str
    access_count: int = 0


class MemoryStore:
    """A bounded SQLite memory store shared by all local runs.

    ``scope`` is normally ``global`` for durable user preferences/facts or ``run:<id>`` for
    context that should follow one long-running goal.  Retrieval always receives an explicit scope
    list so a caller cannot accidentally search another user's state in a future multi-profile
    implementation.
    """

    _TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff-]+", re.UNICODE)

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(MEMORY_SCHEMA)

    @staticmethod
    def _normalize_scope(scope: str) -> str:
        value = scope.strip()
        if not value:
            raise ValueError("memory scope must not be empty")
        if len(value) > 120 or any(char in value for char in "\r\n"):
            raise ValueError("memory scope is invalid")
        return value

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        value = kind.strip() or "note"
        if len(value) > 40 or any(char in value for char in "\r\n"):
            raise ValueError("memory kind is invalid")
        return value

    @staticmethod
    def _normalize_tags(tags: Iterable[str] | None) -> tuple[str, ...]:
        if tags is None:
            return ()
        normalized: list[str] = []
        for tag in tags:
            if not isinstance(tag, str):
                raise TypeError("memory tags must be strings")
            value = tag.strip()
            if value and value not in normalized:
                normalized.append(value[:80])
        return tuple(normalized[:20])

    def remember(
        self,
        content: str,
        *,
        scope: str = "global",
        kind: str = "note",
        tags: Iterable[str] | None = None,
        source: str | None = None,
    ) -> MemoryEntry:
        value = content.strip()
        if not value:
            raise ValueError("memory content must not be empty")
        if len(value.encode("utf-8")) > 20_000:
            raise ValueError("memory content exceeds 20 KiB")
        normalized_scope = self._normalize_scope(scope)
        normalized_kind = self._normalize_kind(kind)
        normalized_tags = self._normalize_tags(tags)
        if source is not None and len(source) > 120:
            raise ValueError("memory source is too long")
        now = datetime.now(UTC).isoformat()
        memory_id = f"memory-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories(id, scope, kind, content, tags, source, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    normalized_scope,
                    normalized_kind,
                    value,
                    json.dumps(normalized_tags, ensure_ascii=False),
                    source,
                    now,
                    now,
                ),
            )
        return MemoryEntry(
            id=memory_id,
            scope=normalized_scope,
            kind=normalized_kind,
            content=value,
            tags=normalized_tags,
            source=source,
            created_at=now,
            updated_at=now,
        )

    def recall(
        self,
        query: str,
        *,
        scopes: Iterable[str] = ("global",),
        limit: int = 8,
    ) -> list[MemoryEntry]:
        if limit < 1:
            return []
        normalized_scopes = tuple(dict.fromkeys(self._normalize_scope(scope) for scope in scopes))
        if not normalized_scopes:
            return []
        query_tokens = {token.lower() for token in self._TOKEN_RE.findall(query) if token}
        placeholders = ",".join("?" for _ in normalized_scopes)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE scope IN ({placeholders})",
                list(normalized_scopes),
            ).fetchall()
            scored: list[tuple[float, sqlite3.Row]] = []
            for row in rows:
                content_lower = row["content"].lower()
                tags = tuple(json.loads(row["tags"] or "[]"))
                tag_lower = " ".join(tags).lower()
                token_hits = sum(
                    1 for token in query_tokens if token in content_lower or token in tag_lower
                )
                phrase_hit = 1 if query.strip() and query.strip().lower() in content_lower else 0
                # Recency is only a tie-breaker.  A memory with no lexical match is still useful
                # for an empty query (the normal "recent context" request).
                score = float(phrase_hit * 100 + token_hits * 10)
                if not query_tokens and not phrase_hit:
                    score = 1.0
                if score > 0:
                    scored.append((score, row))
            scored.sort(key=lambda item: (item[0], item[1]["updated_at"], item[1]["id"]), reverse=True)
            selected = scored[:limit]
            for _, row in selected:
                connection.execute(
                    "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                    (row["id"],),
                )
        return [self._entry_from_row(row) for _, row in selected]

    def list(self, *, scope: str | None = None, limit: int = 100) -> list[MemoryEntry]:
        if limit < 1:
            return []
        with self._connect() as connection:
            if scope is None:
                rows = connection.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                normalized_scope = self._normalize_scope(scope)
                rows = connection.execute(
                    "SELECT * FROM memories WHERE scope = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
                    (normalized_scope, limit),
                ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            scope=row["scope"],
            kind=row["kind"],
            content=row["content"],
            tags=tuple(json.loads(row["tags"] or "[]")),
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            access_count=row["access_count"],
        )
