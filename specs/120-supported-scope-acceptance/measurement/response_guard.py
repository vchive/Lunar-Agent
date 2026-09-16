"""Private bounded assistant-text diagnostics around the unchanged 113 request guard.

This records parsed ModelTurn.text only: no raw HTTP response, reasoning field, prompt,
credential, or model/tool behavior is added. Capture failures are advisory and never change
the native result, the base guard's accounting, or its failure semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat

from runtime_guard import RuntimeGuard as BaseRuntimeGuard

from famou.runtime import _SECRET_RE, ModelTurn

MAX_PREFIX_BYTES = 64 * 1024


def _stage_hint(messages):
    prefixes = (
        ("You are Lunar-Agent's algorithm contract compiler.", "contract_compiler"),
        ("You are compiling one frozen local evaluator bundle", "evaluator_compiler"),
        ("You are an independent adversarial evaluator auditor.", "evaluator_auditor"),
    )
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            for prefix, label in prefixes:
                if content.startswith(prefix):
                    return label
        break
    return "other"


class RuntimeGuard(BaseRuntimeGuard):
    """Keep 113 admission and usage behavior; additionally retain redacted response prefixes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._responses_captured = 0
        self._responses_unavailable = 0

    def _write_response(self, path, payload):
        root = path.parent
        root.mkdir(mode=0o700, exist_ok=True)
        if root.is_symlink() or not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700:
            raise OSError("response directory is unavailable")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False) + "\n"
        with path.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def _capture_response(self, index, runtime, messages, turn):
        try:
            raw = turn.text.encode("utf-8")
            key = getattr(runtime, "api_key", None)
            redacted = turn.text.replace(key, "[REDACTED]") if isinstance(key, str) and key else turn.text
            redacted = _SECRET_RE.sub("[REDACTED]", redacted)
            redacted_bytes = redacted.encode("utf-8")
            prefix = redacted_bytes[:MAX_PREFIX_BYTES].decode("utf-8", errors="ignore")
            prefix_bytes = len(prefix.encode("utf-8"))
            payload = {
                "schema_version": "1", "request_index": index,
                "capture_scope": "parsed_assistant_text_only", "stage_hint": _stage_hint(messages),
                "tool_call_count": len(turn.tool_calls),
                "text_utf8_bytes": len(raw), "text_sha256": hashlib.sha256(raw).hexdigest(),
                "redaction_applied": redacted != turn.text,
                "redacted_prefix": prefix, "redacted_prefix_utf8_bytes": prefix_bytes,
                "truncated": prefix_bytes < len(redacted_bytes),
            }
            path = self.journal_path.parent / "responses" / f"response-{index:03d}.json"
            self._write_response(path, payload)
        except Exception:  # noqa: BLE001 - optional diagnostics cannot alter a native outcome
            self._responses_unavailable += 1
        else:
            self._responses_captured += 1

    def complete(self, native, runtime, messages, tools=(), timeout=None):
        observed = None

        def observed_native(model, request_messages, request_tools=(), request_timeout=None):
            nonlocal observed
            turn = native(model, request_messages, request_tools, request_timeout)
            if isinstance(turn, ModelTurn):
                observed = self.requests, model, request_messages, turn
            return turn

        try:
            return super().complete(observed_native, runtime, messages, tools, timeout)
        finally:
            # Persist after base admission/accounting, so diagnostic latency or failure cannot
            # turn a completed native response into a late-response rejection in this call.
            if observed is not None:
                self._capture_response(*observed)

    def snapshot(self):
        result = super().snapshot()
        result["response_diagnostics"] = {
            "captured": self._responses_captured, "unavailable": self._responses_unavailable,
        }
        return result
