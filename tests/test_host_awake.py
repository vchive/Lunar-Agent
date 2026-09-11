"""Offline assertion ownership, rollback and CoreFoundation boundary coverage."""

import ctypes
import importlib
import os

import pytest

TYPE = "PreventUserIdleSystemSleep"
NAME = "Lunar Agent evaluation"
SECRET = "credential-like-text-must-not-escape"


def awake():
    return importlib.import_module("famou.host_awake")


class FakeAPI:
    def __init__(self, *, identifier=19, properties=None, create_error=None, query_error=None,
                 release_error=None):
        self.identifier = identifier
        self.state = {"assertion_type": TYPE, "level": 255} if properties is None else properties
        self.create_error, self.query_error, self.release_error = (
            create_error, query_error, release_error,
        )
        self.calls = []

    def create(self):
        self.calls.append(("create",))
        if self.create_error is not None:
            raise self.create_error
        return self.identifier

    def properties(self, identifier):
        self.calls.append(("properties", identifier))
        if self.query_error is not None:
            raise self.query_error
        return self.state

    def release(self, identifier):
        self.calls.append(("release", identifier))
        if self.release_error is not None:
            raise self.release_error


def test_injected_api_is_lazy_and_never_loads_ffi(monkeypatch):
    hw = awake()
    monkeypatch.setattr(hw.ctypes, "CDLL", lambda *_: pytest.fail("FFI loaded in offline test"))
    api = FakeAPI()
    guard = hw.MacOSIdleSleepAssertion(api=api)
    assert api.calls == []
    expected = {"backend": "macos_iokit", "assertion_type": TYPE, "assertion_id": 19,
                "owner_pid": os.getpid(), "level": 255, "verified": True}
    assert guard.acquire() == expected
    assert guard.verify() == expected
    guard.release()
    guard.release()
    assert api.calls == [("create",), ("properties", 19), ("properties", 19), ("release", 19)]


@pytest.mark.parametrize("platform", ["linux", "win32", "freebsd"])
def test_unsupported_platform_refuses_before_library_load(monkeypatch, platform):
    hw = awake()
    monkeypatch.setattr(hw.sys, "platform", platform)
    monkeypatch.setattr(hw.ctypes, "CDLL", lambda *_: pytest.fail("must not load frameworks"))
    guard = hw.MacOSIdleSleepAssertion()
    with pytest.raises(hw.HostAwakeError, match="^unsupported_platform$"):
        guard.acquire()
    guard.release()


def test_native_loader_failure_is_safe_and_not_retried(monkeypatch):
    hw = awake()
    monkeypatch.setattr(hw.sys, "platform", "darwin")
    calls = []

    def load(path):
        calls.append(path)
        raise OSError(SECRET)

    monkeypatch.setattr(hw.ctypes, "CDLL", load)
    guard = hw.MacOSIdleSleepAssertion()
    with pytest.raises(hw.HostAwakeError, match="^native_unavailable$") as caught:
        guard.acquire()
    assert SECRET not in str(caught.value)
    guard.release()
    with pytest.raises(hw.HostAwakeError, match="^assertion_reused$"):
        guard.acquire()
    assert len(calls) == 1


@pytest.mark.parametrize("identifier", [0, -1, 2**32, True, 1.5, "19", None])
def test_invalid_assertion_ids_are_never_claimed_or_released(identifier):
    hw = awake()
    api = FakeAPI(identifier=identifier)
    guard = hw.MacOSIdleSleepAssertion(api=api)
    with pytest.raises(hw.HostAwakeError, match="^assertion_create_failed$"):
        guard.acquire()
    guard.release()
    assert api.calls == [("create",)]


@pytest.mark.parametrize("state", [
    {}, {"assertion_type": TYPE, "level": 0}, {"assertion_type": TYPE, "level": True},
    {"assertion_type": TYPE, "level": 255.0}, {"assertion_type": "PreventSystemSleep", "level": 255},
    {"assertion_type": TYPE, "level": 255, "secret": SECRET}, [],
])
def test_unverified_acquisition_rolls_back(state):
    hw = awake()
    api = FakeAPI(properties=state)
    guard = hw.MacOSIdleSleepAssertion(api=api)
    with pytest.raises(hw.HostAwakeError, match="^assertion_verify_failed$"):
        guard.acquire()
    guard.release()
    assert api.calls == [("create",), ("properties", 19), ("release", 19)]


@pytest.mark.parametrize("error", [OSError(SECRET), KeyboardInterrupt(), SystemExit(23)])
def test_query_exception_rolls_back_and_preserves_cancellation(error):
    hw = awake()
    api = FakeAPI(query_error=error)
    guard = hw.MacOSIdleSleepAssertion(api=api)
    with pytest.raises(type(error) if not isinstance(error, Exception) else hw.HostAwakeError) as got:
        guard.acquire()
    if not isinstance(error, Exception):
        assert got.value is error
    else:
        assert str(got.value) == "assertion_verify_failed"
    guard.release()
    assert api.calls.count(("release", 19)) == 1


def test_create_exception_is_safe_without_foreign_release():
    hw = awake()
    api = FakeAPI(create_error=RuntimeError(SECRET))
    guard = hw.MacOSIdleSleepAssertion(api=api)
    with pytest.raises(hw.HostAwakeError, match="^assertion_create_failed$"):
        guard.acquire()
    guard.release()
    assert api.calls == [("create",)]


def test_rollback_failure_remains_owned_until_a_successful_release():
    hw = awake()
    api = FakeAPI(query_error=OSError(SECRET), release_error=OSError(SECRET))
    guard = hw.MacOSIdleSleepAssertion(api=api)
    with pytest.raises(hw.HostAwakeError, match="^assertion_verify_failed$"):
        guard.acquire()
    with pytest.raises(hw.HostAwakeError, match="^assertion_release_failed$"):
        guard.release()
    api.release_error = None
    guard.release()
    guard.release()
    assert api.calls.count(("release", 19)) == 3


def test_repeated_acquire_and_verification_after_release_are_rejected():
    hw = awake()
    api = FakeAPI()
    guard = hw.MacOSIdleSleepAssertion(api=api)
    with pytest.raises(hw.HostAwakeError, match="^assertion_not_acquired$"):
        guard.verify()
    guard.acquire()
    with pytest.raises(hw.HostAwakeError, match="^assertion_reused$"):
        guard.acquire()
    guard.release()
    with pytest.raises(hw.HostAwakeError, match="^assertion_reused$"):
        guard.acquire()
    with pytest.raises(hw.HostAwakeError, match="^assertion_not_acquired$"):
        guard.verify()
    assert api.calls.count(("create",)) == 1


@pytest.mark.parametrize("operation", ["acquire", "verify", "release"])
@pytest.mark.parametrize("acquired", [False, True])
def test_cross_pid_never_operates_on_parent_assertion(monkeypatch, operation, acquired):
    hw = awake()
    api = FakeAPI()
    guard = hw.MacOSIdleSleepAssertion(api=api)
    if acquired:
        guard.acquire()
    before = list(api.calls)
    owner_pid = os.getpid()
    monkeypatch.setattr(hw.os, "getpid", lambda: owner_pid + 1)
    with pytest.raises(hw.HostAwakeError, match="^assertion_pid_mismatch$"):
        getattr(guard, operation)()
    assert api.calls == before


@pytest.mark.parametrize("value", [SECRET, "assertion_verify_failed", "clock_invalid"])
def test_error_has_only_allowlisted_safe_code(value):
    hw = awake()
    error = hw.HostAwakeError(value)
    expected = "host_guard_failed" if value == SECRET else value
    assert isinstance(error, ValueError)
    assert error.code == expected and str(error) == expected and error.args == (expected,)


class CFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = self.restype = "unset"

    def __call__(self, *args):
        assert self.argtypes != "unset" and self.restype != "unset"
        return self.callback(*args)


class FakeFrameworks:
    """Native-shape fake pointers; no system library or OS assertion is loaded."""

    def __init__(self, *, create_status=0, query_kind="valid", create_error=None,
                 release_status=0, null_string_at=None, cf_release_error_at=None):
        self.create_status, self.query_kind, self.create_error = (
            create_status, query_kind, create_error,
        )
        self.release_status, self.null_string_at = release_status, null_string_at
        self.cf_release_error_at = cf_release_error_at
        self.objects = {100: ("dictionary", None), 101: ("string", TYPE), 102: ("number", 255)}
        self.allocated, self.freed, self.native_releases, self.loads = [], [], [], []
        self.created = []
        self.io = type("IO", (), {})()
        self.cf = type("CF", (), {})()
        for name, callback in {
            "IOPMAssertionCreateWithName": self.create,
            "IOPMAssertionCopyProperties": self.properties,
            "IOPMAssertionRelease": self.release,
        }.items():
            setattr(self.io, name, CFunction(callback))
        for name, callback in {
            "CFStringCreateWithCString": self.string,
            "CFRelease": self.free,
            "CFGetTypeID": lambda pointer: {"dictionary": 1, "string": 2, "number": 3}[
                self.objects[pointer][0]],
            "CFDictionaryGetTypeID": lambda: 1,
            "CFStringGetTypeID": lambda: 2,
            "CFNumberGetTypeID": lambda: 3,
            "CFDictionaryGetValue": self.value,
            "CFEqual": lambda first, second: self.objects[first] == self.objects[second],
            "CFNumberGetValue": self.number,
        }.items():
            setattr(self.cf, name, CFunction(callback))

    def load(self, path):
        self.loads.append(path)
        return self.io if path.endswith("/IOKit") else self.cf

    def string(self, allocator, data, encoding):
        assert allocator is None and encoding == 0x08000100
        if len(self.allocated) == self.null_string_at:
            return None
        pointer = 200 + len(self.allocated)
        self.objects[pointer] = ("string", data.decode())
        self.allocated.append(pointer)
        return pointer

    def create(self, kind, level, name, output):
        self.created.append((self.objects[kind][1], level, self.objects[name][1]))
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 19
        if self.create_error is not None:
            raise self.create_error
        return self.create_status

    def properties(self, identifier):
        assert identifier == 19
        if self.query_kind == "missing":
            return None
        if self.query_kind == "wrong_dictionary":
            return 101
        if self.query_kind == "wrong_type":
            self.objects[101] = ("number", 255)
        if self.query_kind == "wrong_level_type":
            self.objects[102] = ("string", "255")
        if self.query_kind == "off":
            self.objects[102] = ("number", 0)
        return 100

    def value(self, dictionary, key):
        assert dictionary == 100
        return {"AssertType": 101, "AssertLevel": 102}.get(self.objects[key][1])

    def number(self, pointer, kind, output):
        assert kind == 3
        ctypes.cast(output, ctypes.POINTER(ctypes.c_int32))[0] = self.objects[pointer][1]
        return self.query_kind != "number_failure"

    def release(self, identifier):
        self.native_releases.append(identifier)
        return self.release_status

    def free(self, pointer):
        self.freed.append(pointer)
        if len(self.freed) == self.cf_release_error_at:
            raise OSError(SECRET)


def test_native_boundary_binds_every_signature_and_releases_owned_cf_objects():
    hw = awake()
    ffi = FakeFrameworks()
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    assert guard.acquire()["verified"] is True
    guard.release()
    assert ffi.created == [(TYPE, 255, NAME)]
    assert ffi.loads == ["/System/Library/Frameworks/IOKit.framework/IOKit",
                         "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"]
    assert sorted(ffi.freed) == sorted([*ffi.allocated, 100])
    assert 101 not in ffi.freed and 102 not in ffi.freed
    assert ffi.native_releases == [19]
    assert ffi.io.IOPMAssertionCreateWithName.restype is ctypes.c_int32
    assert ffi.io.IOPMAssertionCreateWithName.argtypes == [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    for library in (ffi.io, ffi.cf):
        for function in vars(library).values():
            assert function.argtypes != "unset" and function.restype != "unset"


@pytest.mark.parametrize("query_kind", [
    "missing", "wrong_dictionary", "wrong_type", "wrong_level_type", "off", "number_failure",
])
def test_native_query_failures_release_assertion_and_owned_dictionary(query_kind):
    hw = awake()
    ffi = FakeFrameworks(query_kind=query_kind)
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    with pytest.raises(hw.HostAwakeError, match="^assertion_verify_failed$"):
        guard.acquire()
    assert ffi.native_releases == [19]
    if query_kind == "missing":
        assert 100 not in ffi.freed
    elif query_kind == "wrong_dictionary":
        assert 101 in ffi.freed
    else:
        assert 100 in ffi.freed
    assert all(ffi.freed.count(pointer) == 1 for pointer in ffi.allocated)


@pytest.mark.parametrize("null_at", [0, 1, 2, 3])
def test_native_string_allocation_failure_has_no_cf_or_assertion_leak(null_at):
    hw = awake()
    ffi = FakeFrameworks(null_string_at=null_at)
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    with pytest.raises(hw.HostAwakeError):
        guard.acquire()
    assert all(ffi.freed.count(pointer) == 1 for pointer in ffi.allocated)
    assert ffi.native_releases == ([] if null_at < 2 else [19])


@pytest.mark.parametrize("error", [OSError(SECRET), KeyboardInterrupt(), SystemExit(9)])
def test_native_create_cancellation_after_out_id_is_rolled_back(error):
    hw = awake()
    ffi = FakeFrameworks(create_error=error)
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    with pytest.raises(type(error) if not isinstance(error, Exception) else hw.HostAwakeError) as got:
        guard.acquire()
    if not isinstance(error, Exception):
        assert got.value is error
    assert ffi.native_releases == [19]
    assert sorted(ffi.freed) == sorted(ffi.allocated)


def test_native_cf_cleanup_failure_after_create_rolls_back_assertion():
    hw = awake()
    ffi = FakeFrameworks(cf_release_error_at=1)
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    with pytest.raises(hw.HostAwakeError):
        guard.acquire()
    assert ffi.native_releases == [19]
    assert sorted(ffi.freed) == sorted(ffi.allocated)


def test_native_release_error_does_not_claim_success():
    hw = awake()
    ffi = FakeFrameworks(release_status=-1)
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    guard.acquire()
    with pytest.raises(hw.HostAwakeError, match="^assertion_release_failed$"):
        guard.release()
    ffi.release_status = 0
    guard.release()
    guard.release()
    assert ffi.native_releases == [19, 19]


def test_native_failed_create_without_out_id_has_no_assertion_to_release():
    hw = awake()
    ffi = FakeFrameworks()
    ffi.io.IOPMAssertionCreateWithName.callback = lambda *_: -1
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    with pytest.raises(hw.HostAwakeError, match="^assertion_create_failed$"):
        guard.acquire()
    guard.release()
    assert ffi.native_releases == []
    assert sorted(ffi.freed) == sorted(ffi.allocated)


def test_native_partial_create_with_failed_rollback_is_retained_for_scope_cleanup():
    hw = awake()
    ffi = FakeFrameworks(create_error=OSError(SECRET), release_status=-1)
    guard = hw.MacOSIdleSleepAssertion(api=hw._IOKitAPI(loader=ffi.load))
    with pytest.raises(hw.HostAwakeError, match="^assertion_create_failed$"):
        guard.acquire()
    assert ffi.native_releases == [19, 19]
    ffi.release_status = 0
    guard.release()
    guard.release()
    assert ffi.native_releases == [19, 19, 19]


def test_missing_native_symbol_refuses_without_cf_allocation():
    hw = awake()
    ffi = FakeFrameworks()
    del ffi.cf.CFNumberGetValue
    with pytest.raises(hw.HostAwakeError, match="^native_unavailable$"):
        hw._IOKitAPI(loader=ffi.load)
    assert not ffi.allocated and not ffi.created


def test_release_cancellation_is_preserved_and_never_marked_complete():
    hw = awake()
    cancellation = KeyboardInterrupt()
    api = FakeAPI(release_error=cancellation)
    guard = hw.MacOSIdleSleepAssertion(api=api)
    guard.acquire()
    with pytest.raises(KeyboardInterrupt) as caught:
        guard.release()
    assert caught.value is cancellation
    api.release_error = None
    guard.release()
    guard.release()
    assert api.calls.count(("release", 19)) == 2


def test_nonstring_error_code_is_safely_normalized():
    hw = awake()
    error = hw.HostAwakeError({"detail": SECRET})
    assert error.code == str(error) == "host_guard_failed"
