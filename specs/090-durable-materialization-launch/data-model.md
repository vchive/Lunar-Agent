# Data model

The fixed final file is `evolution/materialization/launch-intent.json`; its temporary sibling is
`.launch-intent.json.tmp`. Both are execution-uncertainty evidence and must survive failed writes
or resume. The version-1 canonical intent is bounded to 8 KiB and binds parent run, evolution run,
task, contract digest, selected candidate ID/path/digest, attempt path, runner fingerprint and
effective timeout in seconds. It contains no process completion, PID or output claims.

The deterministic child event ID is `event-materialization-launch-intended-` plus
SHA-256(parent ID, NUL, child ID). Its type is `materialization_launch_intended`; its task owner is
the single evolution task. Its payload binds parent/child, fixed intent path, intent SHA-256 and
size. Event registration is exact and idempotent in SQLite, but controller launch authorization
is never replayable. No separate artifact row is necessary for this bounded control record.

States are absent, partial/unverifiable intent, and complete intent. The latter two prevent new
launch on resume. Complete intent plus a validated terminal result permits cached return or
Feature 089 recovery; it does not independently prove successful execution. Intent evidence is
not deleted after completion, enabling later drift and missing-evidence checks.
