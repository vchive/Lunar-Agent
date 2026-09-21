# Lunar Evolution installation and identity checks

Use Python 3.11 or later, from a full clone of
`https://github.com/vchive/Lunar-Evolution`. The local checkout directory may keep its existing name.

```sh
python -m pip install 'uv==0.11.8'
python -m venv .venv
uv pip install --python .venv/bin/python -e '.[dev,lint]'
.venv/bin/lunar-evolution --help
.venv/bin/python -m lunar_evolution --help
.venv/bin/lunar-evolution run "create a local report" --runtime mock --json
```

The default state directory is `.lunar-evolution` relative to the caller's working directory.
Use `LUNAR_EVOLUTION_HOME` to configure it, or `--home` to override it explicitly. Other user
configuration variables use the same `LUNAR_EVOLUTION_` prefix; existing execution-only `LUNAR_*`
variables retain their documented protocol meaning.

```sh
.venv/bin/python -m pytest tests/test_identity_installation.py
.venv/bin/python tools/run_tests.py --junit-dir .lunar-evolution/test-results
.venv/bin/ruff check src tests tools
```

The installation suite builds a wheel offline and installs it into a separate environment outside
the checkout. It checks package contents and the sole entrypoint, module/CLI help, configuration
precedence, the new content-digest domain, a mock run with status/events, and an actual detached
mock process. No provider is required. Development dependencies must already be in the uv cache.

The complete runner reports current tests, archived historical tests, and frozen registration
tests separately. See [the archive guide](../../docs/history-archive.md) for fixed commits,
integrity checks, offline prerequisites, and why historical results are not current model results.

## Compatibility and recovery

This change replaces the package, command, configuration prefix, and default state path; it does
not provide an old-name alias or automatic state migration. Update callers and install the new
package into a clean environment. New content digests use the `lunar-evolution-case-v1` domain and
must not be compared as equivalent to digests from earlier namespaces.

Existing private state and sealed evidence remain in the external archive recorded in the
[handoff](../../HANDOFF.md). Keep that archive as original evidence. An explicit `--home` selects
working state and may initialize it; it is not a read-only archive viewer. Moving evidence does not
rebind its original absolute paths or inode identities and does not establish resumability.

Git history remains available. Retained older prose has normalized terminology; original commands,
test sources, and sealed measurements must be read at the fixed revisions in the archive index.
