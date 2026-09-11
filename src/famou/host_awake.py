"""Process-owned macOS idle-sleep assertions with a synchronous verification boundary.

This policy permits display sleep and does not prevent lid, explicit or low-battery sleep.
Property queries describe individual instants, not uninterrupted host wakefulness.
"""

from __future__ import annotations

import ctypes
import os
import sys
from contextlib import contextmanager
from threading import RLock

_TYPE = "PreventUserIdleSystemSleep"
_NAME = "Lunar Agent evaluation"
_LEVEL = 255
_IOKIT = "/System/Library/Frameworks/IOKit.framework/IOKit"
_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_SAFE_CODES = frozenset({
    "host_guard_failed", "unsupported_platform", "native_unavailable", "assertion_reused",
    "assertion_pid_mismatch", "assertion_not_acquired", "assertion_create_failed",
    "assertion_verify_failed", "assertion_release_failed", "session_reused",
    "session_pid_mismatch", "journal_invalid", "journal_write_failed", "clock_invalid",
    "assertion_evidence_invalid", "session_cleanup_failed",
})


class HostAwakeError(ValueError):
    """A fixed safe host-policy code; arbitrary native exception prose is never included."""

    def __init__(self, code: str = "host_guard_failed") -> None:
        self.code = code if type(code) is str and code in _SAFE_CODES else "host_guard_failed"
        super().__init__(self.code)


def _valid_id(value: object) -> bool:
    return type(value) is int and 0 < value < 2**32


class _IOKitAPI:
    """Small native boundary; an explicit loader seam supports native-shape offline fakes."""

    def __init__(self, *, loader=None) -> None:
        self.pending_assertion_id: int | None = None
        try:
            load = ctypes.CDLL if loader is None else loader
            self.io = load(_IOKIT)
            self.cf = load(_CORE_FOUNDATION)
            pointer = ctypes.c_void_p
            self._bind(self.io, "IOPMAssertionCreateWithName", ctypes.c_int32,
                       [pointer, ctypes.c_uint32, pointer, ctypes.POINTER(ctypes.c_uint32)])
            self._bind(self.io, "IOPMAssertionCopyProperties", pointer, [ctypes.c_uint32])
            self._bind(self.io, "IOPMAssertionRelease", ctypes.c_int32, [ctypes.c_uint32])
            self._bind(self.cf, "CFStringCreateWithCString", pointer,
                       [pointer, ctypes.c_char_p, ctypes.c_uint32])
            self._bind(self.cf, "CFRelease", None, [pointer])
            self._bind(self.cf, "CFGetTypeID", ctypes.c_ulong, [pointer])
            for name in ("CFDictionaryGetTypeID", "CFStringGetTypeID", "CFNumberGetTypeID"):
                self._bind(self.cf, name, ctypes.c_ulong, [])
            self._bind(self.cf, "CFDictionaryGetValue", pointer, [pointer, pointer])
            self._bind(self.cf, "CFEqual", ctypes.c_ubyte, [pointer, pointer])
            self._bind(self.cf, "CFNumberGetValue", ctypes.c_ubyte,
                       [pointer, ctypes.c_long, pointer])
        except Exception:  # noqa: BLE001 - fixed native-error projection
            raise HostAwakeError("native_unavailable") from None

    @staticmethod
    def _bind(library, name, result, arguments) -> None:
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result

    @contextmanager
    def _resources(self):
        """Release every owned CF reference; cleanup never replaces an active exception."""
        owned = []
        original = None
        try:
            yield owned
        except BaseException as error:
            original = error
            raise
        finally:
            cleanup_error = None
            for pointer in reversed(owned):
                try:
                    self.cf.CFRelease(pointer)
                except BaseException as error:  # noqa: BLE001 - finish all owned cleanup on cancellation
                    if cleanup_error is None:
                        cleanup_error = error
            if cleanup_error is not None and original is None:
                raise cleanup_error

    def _string(self, value: str, owned: list) -> int:
        reference = self.cf.CFStringCreateWithCString(None, value.encode("utf-8"), 0x08000100)
        if not reference:
            raise ValueError("CF allocation failed")
        owned.append(reference)
        if self.cf.CFGetTypeID(reference) != self.cf.CFStringGetTypeID():
            raise ValueError("CF type mismatch")
        return reference

    def create(self) -> int:
        identifier = ctypes.c_uint32(0)
        try:
            with self._resources() as owned:
                kind, name = self._string(_TYPE, owned), self._string(_NAME, owned)
                status = self.io.IOPMAssertionCreateWithName(
                    kind, _LEVEL, name, ctypes.byref(identifier),
                )
                if status != 0 or not _valid_id(identifier.value):
                    raise HostAwakeError("assertion_create_failed")
                self.pending_assertion_id = identifier.value
            return identifier.value
        except BaseException as error:
            # Cancellation can arrive after native creation wrote the out parameter but before
            # Python received its return code. Keep ownership if rollback itself fails.
            if _valid_id(identifier.value):
                self.pending_assertion_id = identifier.value
                try:
                    self.release(identifier.value)
                except BaseException:  # noqa: BLE001, S110 - preserve original; retain pending ownership
                    pass
            if not isinstance(error, Exception):
                raise
            raise HostAwakeError("assertion_create_failed") from None

    def properties(self, identifier: int) -> dict:
        try:
            with self._resources() as owned:
                properties = self.io.IOPMAssertionCopyProperties(identifier)
                if not properties:
                    raise ValueError("missing assertion")
                owned.append(properties)
                if self.cf.CFGetTypeID(properties) != self.cf.CFDictionaryGetTypeID():
                    raise ValueError("CF dictionary required")
                type_key = self._string("AssertType", owned)
                level_key = self._string("AssertLevel", owned)
                expected_type = self._string(_TYPE, owned)
                kind = self.cf.CFDictionaryGetValue(properties, type_key)
                level = self.cf.CFDictionaryGetValue(properties, level_key)
                if (not kind or not level
                        or self.cf.CFGetTypeID(kind) != self.cf.CFStringGetTypeID()
                        or self.cf.CFGetTypeID(level) != self.cf.CFNumberGetTypeID()
                        or not self.cf.CFEqual(kind, expected_type)):
                    raise ValueError("invalid assertion properties")
                value = ctypes.c_int32()
                if not self.cf.CFNumberGetValue(level, 3, ctypes.byref(value)):
                    raise ValueError("invalid assertion level")
                return {"assertion_type": _TYPE, "level": value.value}
        except Exception:  # noqa: BLE001 - fixed native-error projection
            raise HostAwakeError("assertion_verify_failed") from None

    def release(self, identifier: int) -> None:
        try:
            if self.io.IOPMAssertionRelease(identifier) != 0:
                raise ValueError("assertion release failed")
            if identifier == self.pending_assertion_id:
                self.pending_assertion_id = None
        except Exception:  # noqa: BLE001 - fixed native-error projection
            raise HostAwakeError("assertion_release_failed") from None


class MacOSIdleSleepAssertion:
    """Single-use assertion owned by the constructing process, with explicit cleanup.

    ``api`` is an explicit test seam implementing create(), properties(id), and release(id).
    The default native API is loaded lazily on acquire; constructing or importing is read-only.
    """

    def __init__(self, *, api=None) -> None:
        self._api = api
        self._owner_pid = os.getpid()
        self._attempted = False
        self._assertion_id: int | None = None
        self._released = False
        self._lock = RLock()

    def _check_owner(self) -> None:
        if os.getpid() != self._owner_pid:
            raise HostAwakeError("assertion_pid_mismatch")

    def acquire(self) -> dict:
        self._check_owner()
        with self._lock:
            if self._attempted:
                raise HostAwakeError("assertion_reused")
            self._attempted = True
            try:
                if self._api is None:
                    if sys.platform != "darwin":
                        raise HostAwakeError("unsupported_platform")
                    self._api = _IOKitAPI()
                identifier = self._api.create()
                if not _valid_id(identifier):
                    raise HostAwakeError("assertion_create_failed")
                self._assertion_id = identifier
                return self.verify()
            except BaseException as error:
                if self._assertion_id is None and isinstance(self._api, _IOKitAPI):
                    pending = self._api.pending_assertion_id
                    if _valid_id(pending):
                        self._assertion_id = pending
                try:
                    self.release()
                except BaseException:  # noqa: BLE001, S110 - original error wins; release stays retryable
                    pass
                if not isinstance(error, Exception) or isinstance(error, HostAwakeError):
                    raise
                raise HostAwakeError("assertion_create_failed") from None

    def verify(self) -> dict:
        self._check_owner()
        with self._lock:
            if self._assertion_id is None or self._released:
                raise HostAwakeError("assertion_not_acquired")
            try:
                state = self._api.properties(self._assertion_id)
                if (type(state) is not dict or set(state) != {"assertion_type", "level"}
                        or type(state["assertion_type"]) is not str
                        or state["assertion_type"] != _TYPE
                        or type(state["level"]) is not int or state["level"] != _LEVEL):
                    raise ValueError("invalid assertion evidence")
            except Exception:  # noqa: BLE001 - injected/native details never enter host evidence
                raise HostAwakeError("assertion_verify_failed") from None
            return {
                "backend": "macos_iokit", "assertion_type": _TYPE,
                "assertion_id": self._assertion_id, "owner_pid": self._owner_pid,
                "level": _LEVEL, "verified": True,
            }

    def release(self) -> None:
        self._check_owner()
        with self._lock:
            if self._assertion_id is None or self._released:
                return
            try:
                self._api.release(self._assertion_id)
            except Exception:  # noqa: BLE001 - failed cleanup must remain a safe explicit failure
                raise HostAwakeError("assertion_release_failed") from None
            self._released = True
