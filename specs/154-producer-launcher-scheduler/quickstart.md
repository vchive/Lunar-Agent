# Feature 154 quickstart

This feature is currently a specification-only, zero-write slice. The intended first call is a
read-only admission check:

```text
intent = ProducerLaunchIntent(...)
decision = admit_producer_launch(workspace, admission_plan, publication_journal, intent)
```

`decision.status == "admitted"` means that the exact executable bytes, Feature 152 plan,
Feature 153 journal, run/task identity, output root, grouping declaration, and independent
budgets are internally consistent. It does not start a process and does not write an intent,
receipt, lock, marker, archive, state file, or Store row.

The future launch sequence is deliberately separate:

```text
read-only admission
  -> explicit one-time user attestation
  -> exact executable/PID/PGID registration and work gate
  -> producer-result-v1 + explicit groups
  -> Feature 150/151/152 verification and admission
  -> Feature 153 publication transaction
```

An attestation is valid only when its run/parent-task/task tuple, launch-intent digest, executable
bytes, and executable inode identity match the admission. A timeout, missing process evidence,
uncertain cleanup, or changed output is `unknown` and requires explicit recovery; it is never an
automatic producer retry.

No command in this quickstart runs a producer, provider, evaluator, scheduler, or external
campaign. The first implementation must remain provider-free and leave the workspace byte-for-
byte unchanged on both admission success and rejection.
