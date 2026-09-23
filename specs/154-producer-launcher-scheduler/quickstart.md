# Feature 154 quickstart

This feature is a provider-free, zero-write preflight slice. The intended first call is a
read-only consistency check:

```text
intent = ProducerLaunchIntent(..., journal_id=reserved_id, ...)
preflight = preflight_producer_launch(
    workspace,
    intent,
    producer_root=producer_root,
    candidate_integrity_authority=authority,
    expected_run_id=run_id,
    expected_parent_task_id=parent_task_id,
    expected_task_id=task_id,
)
```

`preflight.status == "preflight_passed"` means that the intent agrees with the supplied native
integrity authority and expected IDs, the executable bytes/inode match, and the derived paths and
budgets are safe. It does not start a process, create a plan or journal, or authorize execution.
The caller must supply the authority and expected IDs explicitly; preflight never infers them
from a path or old state.

The future sequence is separate:

```text
read-only preflight
  -> explicit one-time registration attestation
  -> exact executable/PID/PGID registration and work gate
  -> producer-result-v1 + explicit groups
  -> Feature 150/151/152 verification and admission
  -> Feature 153 publication transaction
```

The attestation is valid only when its run/parent-task/task tuple, launch-intent digest,
executable bytes, and executable inode identity match. A timeout, missing process evidence,
uncertain cleanup, or changed output is `unknown` and requires explicit recovery; it is never an
automatic producer retry.

No command in this quickstart runs a producer, provider, evaluator, scheduler, or external
campaign. The first implementation must leave the workspace byte-for-byte unchanged on both
preflight success and rejection.
