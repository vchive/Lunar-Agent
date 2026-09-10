"""Use the sealed two-slot exclusive launcher and native receipt summary."""
from adapter import load_previous

# The loader returns this private module, so all native functions share the same explicit globals.
_bound_module = load_previous("campaign", overrides={"__file__": __file__})


def __getattr__(name):
    return getattr(_bound_module, name)


if __name__ == "__main__":
    import json
    try:
        result = _bound_module.main()
        raise SystemExit(result)
    except Exception as exc:  # noqa: BLE001 - bounded diagnostic excludes provider content
        print(json.dumps({"status": "measurement078_rejected", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
