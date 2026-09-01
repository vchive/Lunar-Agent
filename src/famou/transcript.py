"""Bounded local JSONL conversation history for long-running sessions."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class SessionTranscript:
    """Persist recent model messages without allowing unbounded or credential-bearing history."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_messages: int = 80,
        max_message_bytes: int = 12_000,
        max_total_bytes: int = 1_000_000,
        redactions: tuple[str, ...] = (),
    ) -> None:
        if max_messages < 1 or max_message_bytes < 256 or max_total_bytes < max_message_bytes:
            raise ValueError("invalid transcript bounds")
        self.path = Path(path).expanduser().resolve()
        self.max_messages = max_messages
        self.max_message_bytes = max_message_bytes
        self.max_total_bytes = max_total_bytes
        self.redactions = tuple(secret for secret in redactions if secret)

    def load(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        try:
            raw = self.path.read_bytes()
        except OSError:
            return []
        if len(raw) > self.max_total_bytes * 2:
            raw = raw[-self.max_total_bytes * 2 :]
        messages: list[dict[str, object]] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                messages.append(item)
        return messages[-self.max_messages :]

    def append(self, message: dict[str, object]) -> None:
        normalized = self._normalize(message)
        messages = self.load()
        messages.append(normalized)
        messages = self._compact(messages)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            for item in messages
        )
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _normalize(self, message: dict[str, object]) -> dict[str, object]:
        value = self._redact_value(message)
        if not isinstance(value, dict) or not isinstance(value.get("role"), str):
            raise TypeError("transcript message requires a role")
        return value

    def _redact_value(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[transcript value omitted]"
        if isinstance(value, str):
            for secret in self.redactions:
                value = value.replace(secret, "[REDACTED]")
            encoded = value.encode("utf-8")
            if len(encoded) <= self.max_message_bytes:
                return value
            suffix = "\n[truncated]"
            budget = max(1, self.max_message_bytes - len(suffix.encode("utf-8")))
            return encoded[:budget].decode("utf-8", errors="ignore") + suffix
        if isinstance(value, dict):
            return {str(key): self._redact_value(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item, depth + 1) for item in value[:40]]
        return value

    def _compact(self, messages: list[dict[str, object]]) -> list[dict[str, object]]:
        messages = messages[-self.max_messages :]
        while messages and self._encoded_size(messages) > self.max_total_bytes:
            messages.pop(0)
        # A single structured message can still exceed the file cap due to nested values. Replace
        # its content with a bounded marker rather than violating the total-size contract.
        if messages and self._encoded_size(messages) > self.max_total_bytes:
            messages[-1] = {
                "role": messages[-1].get("role", "system"),
                "content": "[transcript message omitted: size limit]",
            }
        return messages

    @staticmethod
    def _encoded_size(messages: list[dict[str, object]]) -> int:
        return sum(
            len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
            for item in messages
        )
