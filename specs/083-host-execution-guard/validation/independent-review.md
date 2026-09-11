# Feature 083 independent implementation review

Review recorded UTC: 2026-09-11T07:37:33.518449+00:00.

**Verdict: passed; no remaining implementation blocker in the reviewed scope.**

The independent review inspected native assertion ownership and FFI signatures, CLI containment and default compatibility, and the host journal/clock/lifecycle implementation. It modified no product source or tests and did not execute a model, provider, candidate, native assertion, or old campaign audit.

## Verification

Final independent command:

```sh
.venv/bin/python -B -m pytest -o addopts='' -q tests/test_host_awake.py tests/test_host_session.py tests/test_host_execution_cli.py
```

**163 passed in 0.24 seconds** (55 native-boundary, 71 host-session, 37 CLI cases). `git diff --check` also passed. These tests use explicit fake native/guard seams; the CLI integration uses the real journal scope and fake runner/guard without executing the supplied process commands.

## Reviewed fixes and boundaries

- CLI containment compares existing directory device/inode identities and conservatively compares missing suffixes with NFD plus casefold. Workspace and case-source aliases reject before journal creation. The default branch directly calls the original operation without guard import or new path validation; preflight has no guard option.
- Newly opened directory descriptors are tracked immediately. Ownership of the old descriptor is removed before attempting close, so a close that succeeded before cancellation cannot cause a second close of an unrelated reused descriptor number. Failed close remains uncertain and prevents entry. The review independently reproduced the earlier reuse failure using only temporary fixtures; the final regression now preserves the unrelated descriptor.
- Parent-directory fsync and starting/active record fsync precede dispatch. Exclusive journal creation, component and inode checks, prior-byte checks, bounded records, failed persistence and cancellation cleanup are covered. A readable line reports an append attempt and cannot prove its own fsync returned.
- Native CF references and assertion ownership have explicit cleanup. Failed native acquisition/query rolls back where possible; failed cleanup remains an explicit error. HostAwakeError is a safe ValueError subclass handled by the CLI.
- Single-use lifecycle transitions are claimed under RLock. Repeated or concurrent enter/exit cannot clean up another transition. Cross-PID use rejects before taking the lock or touching inherited assertion/journal state. Original work-exception precedence applies inside the owning-process scope.
- Raw signed int64 realtime values, including -2**63, and monotonic brackets remain distinct. Elapsed/divergence bounds preserve clock jumps and uncertainty. Native results, scores, usage ledgers and existing timeout semantics are not changed.

## Existing native smoke evidence

The reviewer read, but did not reexecute, `native-smoke.py` and `native-smoke.json` (JSON SHA256 `69af689d8253ab29d29541c5019a095ceaadc8d2334c41c3f9eb2e8e88b33efb`). All three recorded source/test/script bindings match current bytes. The recorded local smoke covers explicit normal/exceptional release and a child `os._exit(0)` with the owned assertion count observed as 1 before and 0 after exit; it does not test SIGKILL, system sleep, or remote work/billing.

The reviewer also inspected the existing public `host_execution` smoke (`validation/native-scope/result.json`, SHA256 `bad67a704ad3c5d5237b20dff6b7f174564841bf0da1fa5b925918b2dbd1a8c3`) without rerunning it. Its three product-source and script bindings match current bytes. Both journals contain exactly starting/active/closed with consistent PID/session/sequence, work outcome, verified exit observation, and returned release hook; their SHA256 values are `50d29f2ddc8c54afbf0d97a3c5ab40f906bc6297b42b3d4a0409a217e251e24b` (returned) and `9108c56c0a32c76ed2075587479ed2ee69103fdb3aa219421d43a6eec78b21a3` (raised). The script queries that each assertion is absent after exit. An exceptional-body path preserves its original exception even if additional cleanup fails, so its readable closed line and assertion-release query alone must not be interpreted as independent proof that the final journal fsync returned.

## Limits and remaining root validation

Idle-system-sleep prevention permits display, explicit and lid-related sleep as documented. Point-in-time property checks do not prove uninterrupted wakefulness. Missing-name case/normalization comparison intentionally can reject distinct spellings on a case-sensitive filesystem. Descriptor-close failure has uncertain OS outcome and is not retried using a possibly reused number. The root task owns the full regression, old Git seal checks and final commit; this report does not claim those outstanding actions have completed.

## Historical source-fixture compatibility fix

The root full regression exposed one main-suite test that assumed the current checkout still contained the 38 source files from sealed Feature 082. The independent review verified the narrow fix in `tests/test_measurement082_audit.py`: it now reads the fixed 082 implementation commit using local Git blob operations, reconstructs only those bytes under `tmp_path`, and constrains the fake Git responses to that fixture and commit. It calls `check_source(tmp_path)` rather than auditing the current product checkout with old campaign bindings. The complete 38-file source fixture passes, while removing `http_transport.py` from the manifest still rejects even after recomputing the aggregate SHA. Sealed scripts and manifests are not changed by this test fix.

Additional independent command:

```sh
.venv/bin/python -B -m pytest -o addopts='' -q tests/test_measurement082_audit.py
```

**54 passed in 5.50 seconds.** This is an offline fixture test, not a rerun of a sealed live campaign audit. The root full-regression rerun remains a separate validation.

## Reviewed product and test bytes

| File | SHA256 |
| --- | --- |
| `src/famou/host_awake.py` | `da33de0ae15b91729c8352067abbdc4a85cb710560d5f02c51f4e9b1bb4d3afd` |
| `src/famou/host_session.py` | `db63d52cfcab8200c7c895e60a391abe65038daee88e481842a520bb703abc95` |
| `src/famou/cli.py` | `5fb5c723b99428868d0940661397fe7f6765998f89448374b6263e7afcbd8298` |
| `tests/test_host_awake.py` | `5d345a19957493f983e9176e0fce14a3fa3b34d1db3e1e73c690bc8d1d8248eb` |
| `tests/test_host_session.py` | `cbc42f681daf6b634b49dae1cb92037b470946306e79dfcd00e59e6c62cdb017` |
| `tests/test_host_execution_cli.py` | `724264572bf28b224fae87f79b21ed8b98b533cd722786a08a0d9cbdfe8d4eb8` |
| `tests/test_measurement082_audit.py` | `ec6d33540d52cfacad2b8ff6a0e77b1ddeb78af567c8c48d78c9185057504b75` |
