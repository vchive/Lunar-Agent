"""Provider-free cooperative request-level evidence.

``ProducerLaunchIntent.request_timeout_seconds`` is a declaration.  A parent process can
enforce the process wall clock, but it cannot observe provider requests made by an arbitrary
executable.  This module defines the small, bounded payload a trusted producer SDK may emit so
that a later lifecycle adapter can distinguish a syntactically valid declaration from host
enforcement.  Parsing this payload never upgrades it to host-observed evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

PRODUCER_REQUEST_EVIDENCE_PROTOCOL = "lunar-producer-request-evidence-v1"
PRODUCER_REQUEST_EVIDENCE_SCHEMA_VERSION = "1"
MAX_REQUEST_EVIDENCE_BYTES = 256 * 1024
MAX_REQUEST_EVENTS = 16_384
MAX_REQUEST_ID_BYTES = 128
MAX_REQUEST_DURATION_MS = 86_400_000
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "launch_id",
        "journal_id",
        "run_id",
        "parent_task_id",
        "task_id",
        "intent_sha256",
        "request_timeout_seconds",
        "max_requests",
        "observed_request_count",
        "coverage",
        "clock_source",
        "events",
        "evidence_sha256",
    }
)
_EVENT_FIELDS = frozenset({"sequence", "request_id", "status", "duration_ms"})
_STATUSES = frozenset({"completed", "failed", "cancelled", "timed_out"})


class ProducerRequestEvidenceError(ValueError):
    """Bounded fixed-code request evidence failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerRequestEvidenceError(code)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerRequestEvidenceError("producer_request_evidence_canonical_invalid") from exc
    if len(encoded) > MAX_REQUEST_EVIDENCE_BYTES:
        _fail("producer_request_evidence_too_large")
    return encoded


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in items:
        if key in result:
            _fail("producer_request_evidence_duplicate_key")
        result[key] = item
    return result


def _strict_json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProducerRequestEvidenceError("producer_request_evidence_json_invalid") from exc
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_REQUEST_EVIDENCE_BYTES:
        _fail("producer_request_evidence_json_invalid")
    try:
        return json.loads(
            value,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail("producer_request_evidence_json_invalid"),
        )
    except ProducerRequestEvidenceError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProducerRequestEvidenceError("producer_request_evidence_json_invalid") from exc


def _object(value: object, fields: frozenset[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _bounded_int(value: object, *, minimum: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail(code)
    return value


def _digest_without(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class ProducerRequestEvent:
    """One SDK-observed request, with no provider payload or prompt text."""

    sequence: int
    request_id: str
    status: str
    duration_ms: int

    def __post_init__(self) -> None:
        _bounded_int(self.sequence, minimum=1, maximum=MAX_REQUEST_EVENTS, code="producer_request_evidence_sequence_invalid")
        _identifier(self.request_id, "producer_request_evidence_request_id_invalid")
        if len(self.request_id.encode("utf-8")) > MAX_REQUEST_ID_BYTES:
            _fail("producer_request_evidence_request_id_invalid")
        if self.status not in _STATUSES:
            _fail("producer_request_evidence_status_invalid")
        _bounded_int(self.duration_ms, minimum=0, maximum=MAX_REQUEST_DURATION_MS, code="producer_request_evidence_duration_invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "request_id": self.request_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class ProducerRequestEvidence:
    """Canonical cooperative declaration for a single producer launch.

    ``coverage`` is intentionally explicit.  ``partial`` evidence can be retained for
    diagnostics, but it can never establish that the request ceiling was respected.  The
    ``clock_source`` is the producer SDK's monotonic clock; it is not comparable to the
    controller's clock and therefore does not constitute host-side timeout enforcement.
    """

    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    intent_sha256: str
    request_timeout_seconds: int
    max_requests: int
    observed_request_count: int
    coverage: str
    clock_source: str
    events: tuple[ProducerRequestEvent, ...]
    evidence_sha256: str | None = None
    schema_version: str = PRODUCER_REQUEST_EVIDENCE_SCHEMA_VERSION
    protocol: str = PRODUCER_REQUEST_EVIDENCE_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCER_REQUEST_EVIDENCE_SCHEMA_VERSION or self.protocol != PRODUCER_REQUEST_EVIDENCE_PROTOCOL:
            _fail("producer_request_evidence_schema_invalid")
        for value in (self.launch_id, self.journal_id, self.run_id, self.parent_task_id, self.task_id):
            _identifier(value, "producer_request_evidence_identity_invalid")
        _sha(self.intent_sha256, "producer_request_evidence_intent_invalid")
        _bounded_int(self.request_timeout_seconds, minimum=1, maximum=86_400, code="producer_request_evidence_timeout_invalid")
        _bounded_int(self.max_requests, minimum=1, maximum=10_000_000_000, code="producer_request_evidence_budget_invalid")
        _bounded_int(self.observed_request_count, minimum=0, maximum=MAX_REQUEST_EVENTS, code="producer_request_evidence_count_invalid")
        if self.coverage not in {"complete", "partial"}:
            _fail("producer_request_evidence_coverage_invalid")
        if self.clock_source != "producer_sdk_monotonic":
            _fail("producer_request_evidence_clock_invalid")
        if not isinstance(self.events, tuple) or len(self.events) > MAX_REQUEST_EVENTS:
            _fail("producer_request_evidence_events_invalid")
        if self.observed_request_count != len(self.events):
            _fail("producer_request_evidence_count_mismatch")
        expected_sequences = tuple(range(1, len(self.events) + 1))
        if tuple(event.sequence for event in self.events) != expected_sequences:
            _fail("producer_request_evidence_sequence_invalid")
        if len({event.request_id for event in self.events}) != len(self.events):
            _fail("producer_request_evidence_request_id_duplicate")
        if self.evidence_sha256 is None:
            object.__setattr__(self, "evidence_sha256", self.digest())
        elif self.evidence_sha256 != self.digest():
            _fail("producer_request_evidence_digest_mismatch")

    def to_dict(self, *, include_evidence_sha256: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "launch_id": self.launch_id,
            "journal_id": self.journal_id,
            "run_id": self.run_id,
            "parent_task_id": self.parent_task_id,
            "task_id": self.task_id,
            "intent_sha256": self.intent_sha256,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_requests": self.max_requests,
            "observed_request_count": self.observed_request_count,
            "coverage": self.coverage,
            "clock_source": self.clock_source,
            "events": [event.to_dict() for event in self.events],
        }
        if include_evidence_sha256:
            value["evidence_sha256"] = self.evidence_sha256
        return value

    def digest(self) -> str:
        return _digest_without(self.to_dict(), "evidence_sha256")


@dataclass(frozen=True, slots=True)
class ProducerRequestEvidenceAssessment:
    """A conservative assessment that keeps declaration separate from enforcement."""

    status: str
    enforcement: str = "cooperative_declaration"
    request_count: int = 0
    timed_out_count: int = 0


def parse_producer_request_evidence(value: object) -> ProducerRequestEvidence:
    """Parse and validate a bounded request evidence payload without claiming enforcement."""
    if isinstance(value, (str, bytes, bytearray)):
        value = _strict_json(value)
    raw = _object(value, _EVIDENCE_FIELDS, "producer_request_evidence_schema_invalid")
    events_raw = raw.get("events")
    if not isinstance(events_raw, list) or len(events_raw) > MAX_REQUEST_EVENTS:
        _fail("producer_request_evidence_events_invalid")
    events: list[ProducerRequestEvent] = []
    for item in events_raw:
        event = _object(item, _EVENT_FIELDS, "producer_request_evidence_event_invalid")
        try:
            events.append(ProducerRequestEvent(**event))
        except ProducerRequestEvidenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProducerRequestEvidenceError("producer_request_evidence_event_invalid") from exc
    try:
        return ProducerRequestEvidence(**{**raw, "events": tuple(events)})
    except ProducerRequestEvidenceError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerRequestEvidenceError("producer_request_evidence_schema_invalid") from exc


def validate_producer_request_evidence(
    value: ProducerRequestEvidence | object,
    *,
    expected_launch_id: str,
    expected_journal_id: str,
    expected_run_id: str,
    expected_parent_task_id: str,
    expected_task_id: str,
    expected_intent_sha256: str,
    expected_request_timeout_seconds: int,
    expected_max_requests: int,
) -> ProducerRequestEvidence:
    """Bind evidence to one intent and its independent budgets.

    This checks the producer declaration's shape and identity only.  It intentionally does not
    claim that an arbitrary process actually made the requests or that the host enforced timing.
    """
    evidence = value if isinstance(value, ProducerRequestEvidence) else parse_producer_request_evidence(value)
    expected = {
        "launch_id": expected_launch_id,
        "journal_id": expected_journal_id,
        "run_id": expected_run_id,
        "parent_task_id": expected_parent_task_id,
        "task_id": expected_task_id,
        "intent_sha256": expected_intent_sha256,
        "request_timeout_seconds": expected_request_timeout_seconds,
        "max_requests": expected_max_requests,
    }
    if any(getattr(evidence, field) != expected_value for field, expected_value in expected.items()):
        _fail("producer_request_evidence_binding_mismatch")
    return evidence


def assess_producer_request_evidence(
    evidence: ProducerRequestEvidence,
) -> ProducerRequestEvidenceAssessment:
    """Return a declaration-only result suitable for a later lifecycle adapter.

    ``within_declared_limits`` means every observed event reports a duration inside the declared
    request ceiling and the observed count is within the declared request budget.  It remains a
    cooperative declaration even when complete; callers must not present it as host enforcement.
    """
    timed_out = sum(event.status == "timed_out" for event in evidence.events)
    timeout_ms = evidence.request_timeout_seconds * 1000
    durations_ok = all(event.duration_ms <= timeout_ms for event in evidence.events)
    within = (
        evidence.coverage == "complete"
        and evidence.observed_request_count <= evidence.max_requests
        and timed_out == 0
        and durations_ok
    )
    if evidence.coverage != "complete":
        status = "insufficient_evidence"
    elif not within:
        status = "declared_limit_exceeded"
    else:
        status = "within_declared_limits"
    return ProducerRequestEvidenceAssessment(
        status=status,
        request_count=evidence.observed_request_count,
        timed_out_count=timed_out,
    )


__all__ = [
    "MAX_REQUEST_DURATION_MS",
    "MAX_REQUEST_EVENTS",
    "MAX_REQUEST_EVIDENCE_BYTES",
    "PRODUCER_REQUEST_EVIDENCE_PROTOCOL",
    "PRODUCER_REQUEST_EVIDENCE_SCHEMA_VERSION",
    "ProducerRequestEvent",
    "ProducerRequestEvidence",
    "ProducerRequestEvidenceAssessment",
    "ProducerRequestEvidenceError",
    "assess_producer_request_evidence",
    "parse_producer_request_evidence",
    "validate_producer_request_evidence",
]
