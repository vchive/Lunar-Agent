"""Read-only identity of the exact subject console launcher and its HTTP worker.

No model call or credential loader is imported. The only child imports the same editable
package as the console script under the native runner's non-sensitive base environment.
This is an identity check of trusted local code, not a sandbox for hostile Python installs.
"""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import time
from pathlib import Path

_LAUNCHER_BODY = b'''# -*- coding: utf-8 -*-
import sys
from famou.cli import main
if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(main())
'''
_PROBE_SECONDS = 15.0
_MAX_OUTPUT = 32 * 1024
_MODULE_NAMES = ("famou.runtime", "famou.http_transport")
_PROBE = '''
import sys
sys.path[0] = sys.argv[1]
import hashlib, json, ssl
from pathlib import Path
import famou.runtime
import famou.http_transport
modules = {}
for module in (famou.runtime, famou.http_transport):
    path = Path(module.__file__).resolve(strict=True)
    modules[module.__name__] = {
        "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
print(json.dumps({
    "executable": sys.executable,
    "resolved_executable": str(Path(sys.executable).resolve(strict=True)),
    "python_version": sys.version,
    "ssl_version": ssl.OPENSSL_VERSION,
    "modules": modules,
    "worker_command": famou.http_transport._worker_command(17),
}, allow_nan=False, separators=(",", ":")))
'''


def _require(condition):
    if not condition:
        raise ValueError("subject runtime identity mismatch")


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot(repo):
    launcher = repo / ".venv/bin/lunar-agent"
    _require(launcher.is_file() and not launcher.is_symlink() and launcher.resolve() == launcher)
    _require(os.access(launcher, os.X_OK) and launcher.stat().st_size <= 4096)
    raw = launcher.read_bytes()
    shebang, separator, body = raw.partition(b"\n")
    _require(separator == b"\n" and body == _LAUNCHER_BODY and shebang.startswith(b"#!/"))
    interpreter_text = shebang[2:].decode("utf-8")
    _require(interpreter_text and not any(c.isspace() or ord(c) < 32 for c in interpreter_text))
    interpreter = Path(interpreter_text)
    _require(interpreter.is_absolute() and str(interpreter) == interpreter_text)
    _require(interpreter.is_file() and os.access(interpreter, os.X_OK))
    resolved = interpreter.resolve(strict=True)
    modules = {}
    for name in _MODULE_NAMES:
        path = repo / "src/famou" / (name.rsplit(".", 1)[1] + ".py")
        _require(path.is_file() and not path.is_symlink() and path.resolve() == path)
        modules[name] = {"path": str(path), "sha256": _sha(path)}
    return {
        "launcher": {"path": str(launcher), "sha256": hashlib.sha256(raw).hexdigest()},
        "interpreter": {"path": str(interpreter), "resolved_path": str(resolved),
                        "sha256": _sha(resolved)},
        "modules": modules,
    }


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("invalid constant")


def _probe(interpreter, launcher):
    """Run one bounded local import probe; suppress unstructured child output on failure."""
    child = None
    deadline = time.monotonic() + _PROBE_SECONDS
    output = bytearray()
    try:
        child = subprocess.Popen(
            [str(interpreter), "-B", "-c", _PROBE, str(launcher.parent)],
            cwd=launcher.parent, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                 "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("probe timeout")
                block = os.read(child.stdout.fileno(), min(4096, _MAX_OUTPUT + 1 - len(output)))
                if not block:
                    break
                output.extend(block)
                if len(output) > _MAX_OUTPUT:
                    raise ValueError("probe output limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or child.wait(timeout=remaining) != 0 or time.monotonic() >= deadline:
            raise ValueError("probe did not succeed")
        value = json.loads(output, object_pairs_hook=_object, parse_constant=_constant)
        if type(value) is not dict:
            raise ValueError("probe object expected")
        return value
    except (OSError, ValueError, UnicodeError, RecursionError, subprocess.TimeoutExpired):
        raise ValueError("subject runtime probe failed") from None
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait()
            child.stdout.close()


def capture(repo):
    """Return fixed JSON-safe facts for the actual .venv/bin/lunar-agent interpreter."""
    try:
        repo = Path(repo).resolve(strict=True)
        before = _snapshot(repo)
        interpreter = Path(before["interpreter"]["path"])
        facts = _probe(interpreter, Path(before["launcher"]["path"]))
        _require(_snapshot(repo) == before)
        _require(type(facts) is dict and set(facts) == {
            "executable", "resolved_executable", "python_version", "ssl_version",
            "modules", "worker_command",
        })
        _require(facts["executable"] == str(interpreter))
        _require(facts["resolved_executable"] == before["interpreter"]["resolved_path"])
        _require(facts["modules"] == before["modules"])
        worker_command = [str(interpreter), "-I", "-S", "-B",
                          before["modules"]["famou.http_transport"]["path"], "17"]
        _require(facts["worker_command"] == worker_command)
        for key in ("python_version", "ssl_version"):
            _require(type(facts[key]) is str and 0 < len(facts[key]) <= 2048)
            _require(all(ord(c) >= 32 or c in "\n\t" for c in facts[key]))
        return {
            "schema_version": "1", "launcher": before["launcher"],
            "interpreter": {**before["interpreter"], "python_version": facts["python_version"],
                            "ssl_version": facts["ssl_version"]},
            "modules": before["modules"], "worker_command": worker_command,
        }
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("subject runtime identity mismatch") from None


def verify(repo, expected):
    """Reject any interpreter, installed-import, worker command or version drift."""
    # Check static pins before executing a possibly replaced interpreter or importing changed
    # files. capture repeats these checks around the probe to catch an intervening mutation.
    try:
        _require(type(expected) is dict)
        before = _snapshot(Path(repo).resolve(strict=True))
        _require(before["launcher"] == expected["launcher"])
        _require(before["modules"] == expected["modules"])
        _require(all(value == expected["interpreter"][key]
                     for key, value in before["interpreter"].items()))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("subject runtime identity mismatch") from None
    observed = capture(repo)
    _require(observed == expected)
    return observed
