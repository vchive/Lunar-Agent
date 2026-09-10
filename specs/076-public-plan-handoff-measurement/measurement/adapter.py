"""Private, SHA-pinned reuse of the sealed two-slot engine and its complete helper graph."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
IMPLEMENTATION = "96d5a600f03e5401753efc6f579d2ff14fe839be"
CAMPAIGN_ID = "real-eval-glm-5.2-public-plan-20260910"
CAMPAIGN = REPO / ".lunar" / CAMPAIGN_ID
ORDER = [("master_1200", "sheet_metal_nesting"), ("master_1200", "china_post_pickup_optimization")]
POLICIES = {"master_1200": {"master_seconds": 1200, "build_seconds": 2400,
                             "reserve_seconds": 120, "checkpoint_after_rounds": 32}}
EXECUTION = {"waves": [[1, 2]], "concurrency": 2, "subject_outer_seconds": 5430,
             "harness_outer_seconds": 3630, "slot_outer_seconds": 9300}
PREVIOUS_ROOT = REPO / "specs/074-corrected-staged-measurement"
PREVIOUS_FILES = {
    "measurement/adapter.py": "c3d06fddb9939c780bcacb5885fcbc73c35196dbe456ed194c79eb72a1ae2dd0",
    "measurement/audit.py": "2013ef1fdeb8cb8956367b377b709125009654efd17fb62be38efb72e270ef1f",
    "measurement/campaign.py": "7a16807043de1305932c0a6fd37c18885caad4c3ba45ed1b6303db439c2eed88",
    "measurement/dry_run.py": "4eb4d35eb77ca88614169b7141b9b12dbd393ffb8d48f074ef0bebe553303c96",
    "measurement/prepare.py": "270a22a035d1d5c05f8fc32c06883e628483a0a659f7a04d80a2bbfbcf4febfc",
    "measurement/worker.py": "fa9c71e055485fa2589da80efed5177a5b0c1f873d2f59f1d2a99360984515f7",
    "postrun/audit.py": "464ca7457be7d449e90ff3653d6a3ba570dfb4a938c1b84666cdbd2870bdca89",
    "postrun/render_report.py": "855cda56732edcb3ccf5456958468746ab5ff4da32d973f6f4981061c98df9dd",
    "postrun/test_audit.py": "909c90e41aacc7707d56187767799b103faed3240835afc435b3aa0ece8c69b5",
}
PREVIOUS_TESTS = {
    "tests/test_measurement074_runner.py": "2cf145639445ac212403c4be91ad24fdd027ea4ea91856a696086eb3aa7c987b",
    "tests/test_measurement074_audit.py": "4e76237ab287327ec36c7e3bcd4becbc3ee51a4a96f0ebc41d0cb2181ef40c20",
}


def _pinned(root, mapping, relative):
    if relative not in mapping:
        raise ValueError("unknown pinned measurement helper")
    path = root / relative
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise ValueError("unsafe pinned measurement helper")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != mapping[relative]:
        raise ValueError("pinned measurement helper changed")
    return path, raw


# Bootstrap only immutable loader definitions. Importing them neither prepares nor dispatches.
_path, _raw = _pinned(PREVIOUS_ROOT, PREVIOUS_FILES, "measurement/adapter.py")
_previous = ModuleType("_feature076_previous_adapter")
_previous.__file__ = str(_path)
exec(compile(_raw, str(_path), "exec"), _previous.__dict__)  # noqa: S102
_loader = _previous._loader
PRIOR_ROOT, PRIOR_FILES = _previous.PRIOR_ROOT, _previous.PRIOR_FILES
LEGACY_ROOT, LEGACY_FILES = _previous.LEGACY_ROOT, _previous.LEGACY_FILES
HELPER_FILES = {**_previous.HELPER_FILES, **PREVIOUS_TESTS, **{
    (PREVIOUS_ROOT / name).relative_to(REPO).as_posix(): digest
    for name, digest in PREVIOUS_FILES.items()
}}


def load_prior(name, *, overrides=None):
    path, raw = _pinned(PRIOR_ROOT, PRIOR_FILES, f"measurement/{name}.py")
    return _loader._evaluate(path, "_feature076_prior_" + name, {}, raw=raw, overrides=overrides)


def load_prior_postrun():
    path, raw = _pinned(PRIOR_ROOT, PRIOR_FILES, "postrun/audit.py")
    return _loader._evaluate(path, "_feature076_stage_validator", {}, raw=raw)


load_legacy = _loader.load_legacy


def _exports():
    module = ModuleType("_feature076_adapter_exports")
    module.__dict__.update(globals())
    return module


def _load_previous(relative, *, overrides=None):
    path, raw = _pinned(PREVIOUS_ROOT, PREVIOUS_FILES, relative)
    dependencies = {name: (lambda name=name: load_current(name))
                    for name in ("prepare", "audit", "worker", "campaign", "dry_run")}
    dependencies["adapter"] = _exports
    return _loader._evaluate(path, "_feature076_previous_" + relative.replace("/", "_"),
                             dependencies, raw=raw, overrides=overrides)


def load_previous(name, *, overrides=None):
    return _load_previous(f"measurement/{name}.py", overrides=overrides)


def load_previous_postrun(name="audit", *, overrides=None):
    return _load_previous(f"postrun/{name}.py", overrides=overrides)


def load_previous_test(name, *, overrides=None):
    path, raw = _pinned(REPO, PREVIOUS_TESTS, f"tests/test_measurement074_{name}.py")
    return _loader._evaluate(path, "_feature076_previous_test_" + name, {},
                             raw=raw, overrides=overrides)


def load_current(name):
    """Expose the explicitly bound module declared by a thin current wrapper, with no aliases."""
    allowed = {"prepare", "audit", "worker", "campaign", "dry_run"}
    if name not in allowed:
        raise ValueError("unknown measurement wrapper")
    cache = {"adapter": _exports()}

    def get(key):
        if key not in cache:
            path = HERE / f"{key}.py"
            if path.is_symlink() or not path.is_file() or path.resolve() != path:
                raise ValueError("unsafe measurement wrapper")
            dependencies = {item: (lambda item=item: get(item)) for item in (*allowed, "adapter")}
            wrapper = _loader._evaluate(path, "_feature076_" + key, dependencies)
            cache[key] = getattr(wrapper, "_bound_module", wrapper)
        return cache[key]

    return get(name)


def load_worker():
    return load_current("worker")


def load_campaign():
    return load_current("campaign")
