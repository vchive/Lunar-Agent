"""Reuse isolated native fixtures with new bindings and the Master planning-role regression."""
from adapter import HERE, REPO, load_previous

_bound_module = load_previous("dry_run", overrides={"HERE": HERE, "REPO": REPO, "__file__": __file__})
SCENARIOS = {
    "master_role_two_slot_registration_and_actual_bytes": ("tests/test_measurement078_audit.py",),
    "two_slot_exclusive_dispatch_native_receipts_and_no_replacement": ("tests/test_measurement078_runner.py",),
    "master_role_postrun_partial_final_and_phase_evidence": (
        "specs/078-master-planning-role-measurement/postrun/test_audit.py",
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
}
NODES = tuple(dict.fromkeys(node for nodes in SCENARIOS.values() for node in nodes))
TEST_MODULES = tuple(path.relative_to(REPO).as_posix() for path in sorted((REPO / "tests").rglob("*.py"))) + (
    "specs/074-corrected-staged-measurement/postrun/test_audit.py",
    "specs/078-master-planning-role-measurement/postrun/test_audit.py",
)
for _module in (_bound_module, _bound_module.native):
    for _name in ("HERE", "REPO", "SCENARIOS", "NODES", "TEST_MODULES"):
        setattr(_module, _name, globals()[_name])
_original_dry_run = _bound_module.dry_run


def dry_run(manifest_path, campaign_path):
    result = _original_dry_run(manifest_path, campaign_path)
    return {**result, "kind": "feature078_offline_dry_run"}


_bound_module.dry_run = dry_run


def __getattr__(name):
    return getattr(_bound_module, name)


if __name__ == "__main__":
    raise SystemExit(_bound_module.main())
