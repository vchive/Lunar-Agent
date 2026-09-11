"""Materialize fresh inputs using the sealed two-slot preparation contract."""
from adapter import load_previous, load_runtime_identity

# The loader returns this private module, so all native functions share the same explicit globals.
_bound_module = load_previous("prepare", overrides={"__file__": __file__})
_bound_module.subject_runtime = load_runtime_identity()
_bound_module._write_new = _bound_module.write_new


def write_new(path, payload):
    q = _bound_module
    if path == q.CAMPAIGN / "readiness.json":
        payload = {**payload, "subject_runtime": q.subject_runtime.capture(q.REPO)}
    if path.name == "manifest.json":
        payload = {**payload, "limitations": [*payload["limitations"],
            "integrated_079_080_081_measurement_not_isolated_deadline_effect",
            "terminal_diagnostic_is_not_scoring_authority"]}
    return q._write_new(path, payload)


_bound_module.write_new = write_new


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
