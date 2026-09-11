"""Run the unchanged native two-slot worker under this new registration."""
from types import FunctionType

from adapter import REPO, load_previous, load_runtime_identity

# The loader returns this private module, so all native functions share the same explicit globals.
_bound_module = load_previous("worker", overrides={"__file__": __file__})
_native_verify_bindings = _bound_module.verify_bindings
subject_runtime = load_runtime_identity()
read_json, confined, require = _bound_module.read_json, _bound_module.confined, _bound_module.require


def verify_bindings(manifest_path, campaign, manifest, manifest_sha, slot, *, require_started=True):
    _native_verify_bindings(manifest_path, campaign, manifest, manifest_sha, slot, require_started=require_started)
    readiness = confined(campaign, "readiness.json")
    require(readiness.relative_to(REPO).as_posix() in manifest["frozen_files_sha256"])
    subject_runtime.verify(REPO, read_json(readiness)["subject_runtime"])


# Preserve the native main's actual globals, including the worker's rebinding used in tests.
_bound_module._native_verify_bindings = _native_verify_bindings
_bound_module.subject_runtime = subject_runtime
_bound_module.verify_bindings = FunctionType(verify_bindings.__code__, _bound_module.__dict__, "verify_bindings")
_bound_module.verify_bindings.__kwdefaults__ = verify_bindings.__kwdefaults__
_bound_module.native.verify_bindings = _bound_module.verify_bindings


def __getattr__(name):
    return getattr(_bound_module, name)


if __name__ == "__main__":
    import json
    try:
        result = _bound_module.main()
        raise SystemExit(result)
    except Exception as exc:  # noqa: BLE001 - bounded diagnostic excludes provider content
        print(json.dumps({"status": "measurement082_rejected", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
