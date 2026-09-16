# Plan

1. Freeze the runner protocol, input namespace, launch invariants, bounded limits, result fields,
   and fixed error codes.
2. Add immutable runner request/result DTOs and canonical path-free launch identity. Reconstruct
   nested plan/admission values before any filesystem access.
3. Implement preflight checks for admission and plan pins, private workspace/input roots,
   descriptor bytes, executable identity, and disjoint directory inodes.
4. Implement one-shot argv execution with explicit environment, `shell=False`, `DEVNULL`
   stdin, process-group creation, timeout/output ceilings, descendant termination, and reaping.
5. Add offline fixtures for success, non-zero exit, timeout, output overflow, start failure,
   symlink/replacement races, pin mismatch before `Popen`, and absence of Store/evaluator effects.
6. Update public documentation and handoff only after implementation and full regression.

## Decisions

The staged input tree remains a separate read-only namespace. A reserved environment variable is
the only discovery mechanism, making the source workspace layout stable and preventing input
bytes from changing source bundle identity. The runner never trusts a previously verified result;
it rechecks bytes and directory identity at launch.

Execution is deliberately weaker than authorization: a successful process does not prove that
the candidate obeyed the contract, that dependencies were authentic, or that an evaluator would
accept its output. Those claims belong to later receipt/evaluator features.

## Complexity tracking

No database migration, Candidate mutation, score calculation, evaluator/provider call, package
installation, network operation, or framework integration is introduced. Process cleanup must
bound waits and report uncertainty rather than silently converting it to success.
