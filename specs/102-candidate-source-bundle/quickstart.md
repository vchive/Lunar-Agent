# Offline source bundle validation

From the repository with its development environment installed, run this self-contained fixture.
It creates a physical temporary directory and uses the installed CLI; it never runs the candidate.

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from famou import parse_candidate_source_bundle
from famou.algorithm import AlgorithmProblemContract

root = Path(tempfile.mkdtemp(prefix="lunar-source-bundle-")).resolve()
source = root / "source"
source.mkdir()
sources = {
    "main.py": (
        b"from pathlib import Path\nfrom helper import answer\n"
        b"Path(__file__).with_name('executed.marker').write_text(str(answer))\n"
    ),
    "helper.py": b"answer = 42\n",
}
contract = AlgorithmProblemContract.from_dict({
    "schema_version": "1", "problem_id": "bundle-example", "problem_type": "routing",
    "statement": "Produce a route program.",
    "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
    "decision_variables": ["route order"],
    "objective": {"name": "quality", "direction": "maximize"},
    "hard_constraints": [], "soft_constraints": [],
    "success_criteria": ["All items are served."], "deliverables": ["A route program."],
})
contract_path = root / "contract.json"
contract_path.write_text(contract.canonical_json(), encoding="utf-8")
for name, content in sources.items():
    (source / name).write_bytes(content)
bundle = parse_candidate_source_bundle({
    "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
    "contract_sha256": contract.digest(), "entrypoint": "main.py",
    "files": [
        {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in sources.items()
    ],
})
manifest = root / "bundle.json"
manifest.write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
home = root / "unused-home"
command = [
    str(Path(".venv/bin/lunar-agent").absolute()), "candidate-bundle", "validate", str(manifest),
    "--source-root", str(source), "--contract", str(contract_path),
    "--bundle-sha256", bundle.digest(), "--home", str(home), "--json",
]
success = subprocess.run(command, capture_output=True, text=True, check=True)
result = json.loads(success.stdout)
assert result == {
    "status": "validated", "bundle_sha256": bundle.digest(),
    "contract_sha256": contract.digest(), "file_count": 2,
    "total_bytes": sum(map(len, sources.values())),
}
(source / "helper.py").write_bytes(b"answer = 43\n")
failure = subprocess.run(command, capture_output=True, text=True)
assert failure.returncode == 2 and failure.stdout == ""
assert json.loads(failure.stderr) == {"error": "candidate_bundle_source_changed"}
assert not home.exists() and not (source / "executed.marker").exists()
print(success.stdout.strip())
print(failure.stderr.strip())
print(f"Fixture retained at {root}")
PY
```

`--bundle-sha256` is optional. Retain the canonical `bundle.digest()` separately when a caller
needs to require that exact declaration. Hashing pretty-printed manifest bytes gives a different
digest. The CLI output deliberately contains no source text or file paths; `--home` is accepted
but does not initialize state. Invalid contract files return `candidate_bundle_contract_invalid`.
The contract is parsed and pinned; its declared problem input files are not inspected by this
source-only command.

Paths must use physical directories without symlink ancestors or `..`; on macOS `/tmp` and `/var`
may be aliases. Manifest paths must be NFC relative POSIX names with no empty/dot/parent components,
Unicode Cc/Cf/Cs characters, colon, backslash or `.git` component. Component case aliases and
file/directory conflicts are rejected. Empty UTF-8 files are allowed; NUL or invalid UTF-8 is not.
Only declared files are checked. This validates neither import closure nor runtime, dependencies,
environment, producer identity, syntax, algorithm quality or a complete repository snapshot.

Run the focused regression with:

```bash
.venv/bin/python -m pytest -o addopts='' -q tests/test_candidate_bundle*.py
```
