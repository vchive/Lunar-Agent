# Implementation plan

1. Inventory current identity surfaces and compute the historical measurement/test dependency
   closure. Pin its immutable pre-migration revision and preserve private artifacts externally.
2. Separate archived evidence and regressions from current product files. Adapt the regression
   runner to restore the pinned checkout outside the working tree and report each phase.
3. Apply one coordinated package/path/text migration, then independently review product entry
   points, environment handling, background module launches, domain hashes and public exports.
4. Update the user-facing name, commands and configuration examples. Use neutral descriptions
   for external references. Retain an explicit archive index instead of altered historical seals.
5. Build a wheel and test a clean external installation, including a real mock background run.
   Run the full current/archived/frozen regression phases and the name/integrity scans.
6. Record validation, update the handoff, commit and push. The remote repository name stays under
   the user's control.

No new runtime dependency or database migration is required. A new namespace is intentionally
not a backward-compatible command alias. Evidence preservation uses Git and filesystem archives;
it does not regenerate historical measurements or relax admission checks.

## Alternatives and validation

A display-only rename or command alias leaves the old package and generated launchers in the
current repository, so it does not meet the user's request. Rewriting sealed manifests would
destroy historical evidence. The chosen split keeps current product tests on the new package and
runs the exact historical tests at their fixed commits outside the checkout.

No database schema or model API contract changes are required. Package imports, command names,
user configuration, default state location and content-digest domains are deliberate compatibility
changes. The [quickstart](quickstart.md) documents fresh installation and recovery limits;
[validation](validation.md) records clean-wheel execution, three regression phases, preserved
inventories and independent review. The archive index is evidence lookup metadata, not launch
authority or permission to resume an old execution.
