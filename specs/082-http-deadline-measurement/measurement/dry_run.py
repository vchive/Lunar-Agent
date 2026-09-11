"""Run fixed offline fixtures; the inherited Python audit guard does not cross exec."""
from adapter import HERE, REPO, load_previous

_bound_module = load_previous("dry_run", overrides={"HERE": HERE, "REPO": REPO, "__file__": __file__})
SCENARIOS = {
    "http_deadline_two_slot_registration_and_actual_bytes": ("tests/test_measurement082_audit.py",),
    "subject_shebang_interpreter_import_and_http_helper_identity": ("tests/test_measurement082_runtime.py",),
    "two_slot_exclusive_dispatch_native_receipts_and_no_replacement": ("tests/test_measurement082_runner.py",),
    "http_deadline_postrun_native_failure_and_v4_diagnostic_evidence": (
        "specs/082-http-deadline-measurement/postrun/test_audit.py",
    ),
    "master_role_verbatim_context_and_unchanged_native_handoff": (
        "tests/test_master_planning_role_integration.py",
    ),
    "public_objective_vocabulary_raw_fenced_and_invalid_native_receipts": (
        "tests/test_master_plan_envelope_integration.py", "tests/test_master_plan_vocabulary.py",
    ),
    "staged_cli_shared_ceilings_and_cooperative_resume": (
        "tests/test_staged_cli.py", "tests/test_staged_workflow.py", "tests/test_staged_agent_loop.py",
        "tests/test_measurement072_stages.py",
    ),
    "prior_actual_input_source_and_harness_byte_validators": ("tests/test_measurement072_audit.py",),
    "subject_failure_never_authorizes_harness": (
        "tests/test_dry_run069.py::test_native_offline_scenario[missing_usage]",
        "tests/test_dry_run069.py::test_native_offline_scenario[timeout]",
    ),
    "finite_deadline_with_pure_ipc_children_and_no_http_dispatch": (
        "tests/test_http_transport_deadline.py::test_request_pipe_blockage_obeys_same_deadline",
        "tests/test_http_transport_deadline.py::test_late_failure_projection_also_checks_transport_deadline",
        "tests/test_http_transport_deadline.py::test_deeply_nested_malformed_worker_ipc_is_a_safe_typed_failure",
    ),
    "deterministic_v3_v4_projection_and_legacy_compatibility": (
        "tests/test_model_request_timing.py::test_observation_is_frozen_and_manual_failure_remains_v3",
        "tests/test_model_request_timing.py::test_failed_observation_construction_preserves_original_failure",
        "tests/test_model_failure_evidence.py::test_legacy_diagnostics_remain_unchanged_and_model_evidence_cannot_be_runtime_budget",
        "tests/test_subject_diagnostics.py",
    ),
}
NODES = tuple(dict.fromkeys(node for nodes in SCENARIOS.values() for node in nodes))
TEST_MODULES = tuple(path.relative_to(REPO).as_posix() for path in sorted((REPO / "tests").rglob("*.py"))) + (
    "specs/074-corrected-staged-measurement/postrun/test_audit.py",
    "specs/082-http-deadline-measurement/postrun/test_audit.py",
)
for _module in (_bound_module, _bound_module.native):
    for _name in ("HERE", "REPO", "SCENARIOS", "NODES", "TEST_MODULES"):
        setattr(_module, _name, globals()[_name])
_original_dry_run = _bound_module.dry_run


def dry_run(manifest_path, campaign_path):
    result = _original_dry_run(manifest_path, campaign_path)
    return {**result, "kind": "feature082_offline_dry_run", "guard_scope": {
        "python_audit_hook": "pytest_process_only_not_exec_descendants",
        "selected_http_children": "fixed_pure_ipc_fixtures_without_http_dispatch",
        "real_loopback_transport_tls_tests": "separate_focused_validation_not_this_guarded_run",
    }}


_bound_module.dry_run = dry_run


def __getattr__(name):
    return getattr(_bound_module, name)


if __name__ == "__main__":
    raise SystemExit(_bound_module.main())
