"""Consume the single registered Feature 139 attempt.

The worker is deliberately thin: registration owns the launch trust root, the
native CLI owns preparation and evolution, and ``analysis.inspect_product`` is
the read-only authority that gates local holdouts on complete parent delivery.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover - exercised by supervision
    _HERE = Path(__file__).resolve().parent
    _PACKAGE = "_lunar_measurement139_worker"
    _spec = importlib.util.spec_from_file_location(
        _PACKAGE, _HERE / "__init__.py", submodule_search_locations=[str(_HERE)],
    )
    if _spec is None or _spec.loader is None:
        raise RuntimeError("measurement_package_unavailable")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_PACKAGE] = _module
    _spec.loader.exec_module(_module)
    __package__ = _PACKAGE

from .analysis import inspect_product, verified_preparation
from .campaign import default_manifest
from .case import ATTEMPT_ID, GOAL, INPUT_BYTES, MODEL, audit_holdouts
from .native_trace import traced_native
from .observation import RuntimeGuard, load_provider, observed_guard
from .registration import default_repository
from .runner import MANIFEST, REPO, canonical, sha, write_new


def verify(*, committed: bool = True) -> dict[str, object]:
    """Return the manifest only after the durable registration trust-root check."""
    return default_repository().verify(committed=committed).manifest


def _error_class(exc: BaseException) -> str:
    for cls in (OSError, ValueError, TypeError, RuntimeError):
        if isinstance(exc, cls):
            return cls.__name__
    return "Exception"


def _write_input(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(INPUT_BYTES)
        stream.flush()
        os.fsync(stream.fileno())


def _read_marker(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("attempt_marker_invalid") from exc
    if type(value) is not dict:
        raise ValueError("attempt_marker_invalid")
    return value


def _admission(
    path: Path,
    manifest: dict[str, object],
    registration_commit: str,
) -> dict[str, object]:
    """Validate the durable slot marker emitted by ``RegistrationRepository``."""
    value = _read_marker(path)
    expected = {
        "schema_version": "1",
        "registration_id": manifest["registration_id"],
        "campaign_id": manifest["campaign_id"],
        "attempt_id": manifest["attempt_id"],
        "registration_commit": registration_commit,
        "manifest_sha256": sha(MANIFEST),
    }
    if set(value) != {*expected, "admitted_utc"} or any(
        type(value.get(key)) is not type(expected_value) or value.get(key) != expected_value
        for key, expected_value in expected.items()
    ) or type(value.get("admitted_utc")) is not str or not value["admitted_utc"]:
        raise ValueError("admission_binding_changed")
    return value


def _started(
    path: Path,
    manifest: dict[str, object],
    registration_commit: str,
    *,
    index: int | None,
) -> dict[str, object]:
    """Validate a root/attempt start marker without accepting a partial shape."""
    value = _read_marker(path)
    expected = {
        "registration_id": manifest["registration_id"],
        "campaign_id": manifest["campaign_id"],
        "attempt_id": manifest["attempt_id"],
        "registration_commit": registration_commit,
        "manifest_sha256": sha(MANIFEST),
    }
    if index is not None:
        expected["index"] = index
    if set(value) != {*expected, "started_utc"} or any(
        type(value.get(key)) is not type(expected_value) or value.get(key) != expected_value
        for key, expected_value in expected.items()
    ) or type(value.get("started_utc")) is not str or not value["started_utc"]:
        raise ValueError("attempt_marker_invalid")
    return value


def _budgets(manifest: dict[str, object]) -> dict[str, object]:
    value = manifest.get("budgets")
    if type(value) is not dict:
        raise ValueError("registered_budgets_missing")
    expected = default_manifest()["budgets"]
    if set(value) != set(expected) or any(
        type(value[key]) is not int or value[key] != item for key, item in expected.items()
    ):
        raise ValueError("registered_budgets_changed")
    return value


def _population(manifest: dict[str, object]) -> dict[str, object]:
    value = manifest.get("population")
    if type(value) is not dict:
        raise ValueError("registered_population_missing")
    expected = default_manifest()["population"]
    if set(value) != set(expected) or any(
        type(value[key]) is not int or value[key] != item for key, item in expected.items()
    ):
        raise ValueError("registered_population_changed")
    return value


def _runtime_options(manifest: dict[str, object]) -> dict[str, object]:
    value = manifest.get("runtime_options")
    if type(value) is not dict:
        raise ValueError("registered_runtime_options_missing")
    expected = {
        "entrypoint": "solve --evolve --multi-file", "runtime": "openai-compatible",
        "model": MODEL, "agent_loop": True, "max_steps": 12,
        "candidate_generation_max_steps": 12, "workers": 1, "max_retries": 1,
        "memory": False, "session_history": False, "allow_exec": False,
        "generated_contract": True, "evaluator_invocation": "snapshot", "terminal_resume": False,
    }
    if set(value) != {*expected, "launch_argv"} or any(
        type(value[key]) is not type(item) or value[key] != item for key, item in expected.items()
    ):
        raise ValueError("registered_runtime_options_changed")
    return value


def _launch_template(manifest: dict[str, object]) -> list[str]:
    options = _runtime_options(manifest)
    template = options.get("launch_argv")
    if type(template) is not list or any(type(item) is not str for item in template):
        raise ValueError("registered_launch_argv_changed")
    expected = [
        "solve", GOAL, "--evolve", "--multi-file",
        "--workspace", "{workspace}", "--home", "{home}",
        "--runtime", "openai-compatible", "--model", "{model}",
        "--agent-loop", "--max-steps", "12",
        "--candidate-generation-max-steps", "12", "--workers", "1",
        "--population-size", "1", "--offspring-per-iteration", "1",
        "--islands", "1", "--max-rounds", "1", "--stagnation-rounds", "3",
        "--seed", "139", "--timeout", "600",
        "--evaluator-preparation-timeout", "900",
        "--evaluator-preparation-wall-timeout", "1860", "--json",
        "--input", "{input}",
    ]
    if template != expected:
        raise ValueError("registered_launch_argv_changed")
    return template


def _holdout_gate(slot: Path) -> bool:
    """Require read-only proof of complete parent delivery before holdouts."""
    product = inspect_product(slot)
    return bool(
        product.get("product_success") is True
        and product.get("primary_valid_completion") is True
        and product.get("closure_verified") is True
        and product.get("preparation_verified") is True
        and product.get("contract_verified") is True
        and product.get("delivery_verified") is True
        and product.get("source_evidence_verified") is True
        and product.get("source_check_validity") is True
        and product.get("source_python_count", 0) >= 2
    )


def _args(manifest: dict[str, object], slot: Path, model: str) -> list[str]:
    _budgets(manifest)
    _population(manifest)
    template = _launch_template(manifest)
    values = {
        "{workspace}": str(slot / "workspace"),
        "{home}": str(slot / "home"),
        "{model}": model,
        "{input}": str(slot / "inputs/limit.json"),
    }
    return [values.get(item, item) for item in template]


def main() -> int:
    started = time.monotonic()
    slot: Path | None = None
    manifest: dict[str, object] | None = None
    guard = None
    rows: list[dict[str, object]] = []
    stage = "setup"
    result: dict[str, object] = {
        "status": "failed", "stage": stage, "frozen": None, "holdouts": rows,
        "native_exit_code": None, "solve_error_class": None,
        "preparation_error_class": None, "error_class": None,
    }
    try:
        verified = default_repository().verify(committed=True)
        manifest = verified.manifest
        registration_commit = verified.registration_commit
        root = REPO / str(manifest["campaign_root"])
        slot = root / str(manifest.get("attempt_id", ATTEMPT_ID))
        _admission(root / "admission.json", manifest, registration_commit)
        _admission(slot / "admission.json", manifest, registration_commit)
        _started(root / "started.json", manifest, registration_commit, index=None)
        _started(slot / "started.json", manifest, registration_commit, index=1)
        if any(path.exists() for path in (
            root / "finished.json", slot / "finished.json", slot / "worker-finished.json",
        )):
            raise ValueError("attempt_already_finished")
        write_new(slot / "worker-started.json", {
            "manifest_sha256": sha(MANIFEST), "campaign_id": manifest["campaign_id"], "index": 1,
        })

        inputs = slot / "inputs"
        _write_input(inputs / "limit.json")
        task = manifest.get("task_utf8")
        if (task != GOAL or manifest.get("input_utf8") != INPUT_BYTES.decode("utf-8")
                or sha(inputs / "limit.json") != manifest.get("input_sha256")):
            raise ValueError("registered_input_or_goal_changed")

        safe_provider = manifest.get("provider_safe_metadata")
        if type(safe_provider) is not dict:
            raise ValueError("registered_provider_missing")
        model = safe_provider.get("model", MODEL)
        if type(model) is not str or not model:
            raise ValueError("registered_provider_missing")
        # Validate every provider-independent launch setting before loading the
        # provider. A malformed registration must not trigger provider setup.
        budgets = _budgets(manifest)
        _population(manifest)
        _runtime_options(manifest)
        native_args = _args(manifest, slot, model)
        provider = load_provider(requested_model=model, expected=safe_provider)
        remaining = float(budgets["wall_seconds"]) - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("attempt_deadline_reached")
        guard = RuntimeGuard(
            provider, model, slot / "calls.jsonl",
            max_requests=budgets["max_requests"],
            token_stop_threshold=budgets["observed_token_stop"],
            wall_seconds=remaining,
            request_seconds=budgets["request_timeout_seconds"],
            preparation_request_seconds=budgets["preparation_request_timeout_seconds"],
        )

        def continuation() -> None:
            if time.monotonic() - started >= float(budgets["wall_seconds"]):
                raise ValueError("acceptance_continuation_stopped")

        from famou.cli import main as native_main

        stage = "solve"
        try:
            with (
                traced_native(guard), observed_guard(guard),
                (slot / "cli.json").open("x", encoding="utf-8") as stream,
            ):
                os.chmod(stream.name, 0o600)
                with contextlib.redirect_stdout(stream):
                    result["native_exit_code"] = native_main(native_args)
        except Exception as exc:  # noqa: BLE001 - retain only fixed diagnostic classes
            result["solve_error_class"] = _error_class(exc)

        stage = "preparation_check"
        result["stage"] = stage
        try:
            contract, bundle = verified_preparation(slot)
        except Exception as exc:  # noqa: BLE001 - no fallback/replay/repair
            result["preparation_error_class"] = _error_class(exc)
        else:
            frozen = {
                "fingerprint": bundle.fingerprint,
                "contract_sha256": bundle.contract_sha256,
                "input_profile_sha256": bundle.input_profile_sha256,
                "files": {path.name: sha(path) for path in sorted(bundle.root.iterdir())},
            }
            result["frozen"] = frozen
            write_new(slot / "frozen.json", frozen)

            # Parent delivery is authoritative.  A preparation snapshot alone never
            # authorizes holdouts because it says nothing about candidate delivery.
            stage = "holdout_gate"
            if not _holdout_gate(slot):
                result["stage"] = "holdout_gate"
            else:
                stage = "holdouts"

                def record(row: dict[str, object]) -> None:
                    write_new(slot / "holdouts" / f"{len(rows) + 1:03d}.json", row)
                    rows.append(row)

                audit_holdouts(
                    bundle, contract, slot / "holdout-workspaces",
                    timeout=budgets["holdout_seconds"], continuation_guard=continuation, record=record,
                )
                continuation()
                if (result["native_exit_code"] == 0 and result["solve_error_class"] is None
                        and len(rows) == 8 and all(row.get("matched") is True for row in rows)):
                    result.update(status="completed", stage="finished")
                else:
                    result["stage"] = "holdouts"
    except Exception as exc:  # noqa: BLE001 - public evidence keeps only a fixed class
        result.update(status="failed", stage=stage, error_class=_error_class(exc))

    result.update(
        guard=guard.snapshot() if guard is not None else None,
        elapsed_seconds=max(0.0, time.monotonic() - started),
    )
    if slot is not None and slot.is_dir() and not (slot / "worker-finished.json").exists():
        write_new(slot / "worker-finished.json", result)
    print(canonical({
        "status": result["status"], "stage": result["stage"],
        "native_exit_code": result["native_exit_code"],
        "frozen": result["frozen"] is not None,
        "holdouts_executed": sum(row.get("snapshot_started") is True for row in rows),
    }), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
