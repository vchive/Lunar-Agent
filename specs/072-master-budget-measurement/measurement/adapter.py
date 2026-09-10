"""Explicit private reuse of pinned Feature069 helpers; imports never alias sys.modules."""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAMPAIGN_ID = "real-eval-glm-5.2-master-budget-20260910"
CAMPAIGN = REPO / ".lunar" / CAMPAIGN_ID
IMPLEMENTATION = "5c89e049c184c52090f665131e3290ea3359bc04"
ORDER = [("master_300", "sheet_metal_nesting"), ("master_1200", "china_post_pickup_optimization"),
         ("master_1200", "sheet_metal_nesting"), ("master_300", "china_post_pickup_optimization")]
POLICIES = {name: {"master_seconds": seconds, "build_seconds": 2400,
                   "reserve_seconds": 120, "checkpoint_after_rounds": 32}
            for name, seconds in (("master_300", 300), ("master_1200", 1200))}
EXECUTION = {"waves": [[1, 2], [3, 4]], "concurrency": 2, "subject_outer_seconds": 5430,
             "harness_outer_seconds": 3630, "slot_outer_seconds": 9300}
LEGACY_ROOT = REPO / "specs/069-webagent-normal-workflow"
LEGACY_FILES = {
    "measurement/audit.py": "2188dddfd687e8f04aa5a7f356339fd7dfa5e0eae05f7a8f77a3f39478b41c15",
    "measurement/campaign.py": "00393a35e852ed253aea80513308cf11a9fe96e92faf8b241314ef435cbc3b71",
    "measurement/dry_run.py": "5f5277b617fd3eaf76b939a163a647a1ffa8c049ddd4b7910ff139b937073733",
    "measurement/prepare.py": "ac1da9d854d2719be35b19c9d6487a40567c20d51ef10852d25c3ea8d3a83604",
    "measurement/worker.py": "446e42ad1cf72d852bbf01c2259dfd42d0f21cef917f99def45f702dbc6b8d08",
    "postrun/audit.py": "a95bff3584765587b965cf8485add6fd1615978e09ac424c497b31b65e25168f",
    "postrun/render_report.py": "09904bc4c680c4374b4d5b83e9a4b954091cc06b5161cc80eec4a84fb568ef5f",
}


def _evaluate(path, name, dependencies, *, raw=None, overrides=None):
    """Evaluate source with an explicit import map, without pyc reads/writes or global aliases."""
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__spec__ = importlib.util.spec_from_file_location(name, path)
    original_import = builtins.__import__
    imported = {}

    def private_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name in dependencies:
            if name not in imported:
                imported[name] = dependencies[name]()
            return imported[name]
        return original_import(name, globals, locals, fromlist, level)

    module.__dict__["__builtins__"] = {**vars(builtins), "__import__": private_import}
    code = compile(path.read_bytes() if raw is None else raw, str(path), "exec")
    exec(code, module.__dict__)  # noqa: S102 - explicit trusted source loader, never model content
    module.__dict__.update(overrides or {})
    return module


def load_legacy(name, *, overrides=None):
    """Load one immutable helper under a private identity; no preparation/launch is invoked."""
    aliases = {"preaudit": "measurement/audit.py", "postrun": "postrun/audit.py",
               "render_report": "postrun/render_report.py"}
    relative = aliases.get(name, f"measurement/{name}.py")
    if relative not in LEGACY_FILES:
        raise ValueError("unknown pinned measurement helper")
    path = LEGACY_ROOT / relative
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise ValueError("unsafe pinned measurement helper")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LEGACY_FILES[relative]:
        raise ValueError("pinned measurement helper changed")
    dependencies = {key: (lambda key=key: load_legacy(key)) for key in ("prepare", "worker")}
    return _evaluate(path, "_feature072_legacy_" + name, dependencies, raw=raw, overrides=overrides)


def load_current(name):
    """Load a private graph of new wrappers, including lazy CLI audit/dry-run dependencies."""
    allowed = {"prepare", "worker", "campaign", "audit", "dry_run"}
    if name not in allowed:
        raise ValueError("unknown measurement wrapper")
    adapter = ModuleType("_feature072_adapter_exports")
    adapter.__dict__.update(globals())
    cache = {"adapter": adapter}

    def get(key):
        if key not in cache:
            path = HERE / f"{key}.py"
            if path.is_symlink() or not path.is_file() or path.resolve() != path:
                raise ValueError("unsafe measurement wrapper")
            dependencies = {item: (lambda item=item: get(item)) for item in (*allowed, "adapter")}
            cache[key] = _evaluate(path, "_feature072_" + key, dependencies)
        return cache[key]

    return get(name)


def load_worker():
    return load_current("worker")


def load_campaign():
    return load_current("campaign")
