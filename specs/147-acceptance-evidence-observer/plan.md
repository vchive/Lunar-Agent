# Implementation plan

1. Keep the observer as a pure parser over in-memory canonical JSON; no provider,
   subprocess, evaluator, Store write, or campaign launch is reachable from its API.
2. Bind a manifest draft to the fixed Feature 142 observation budgets and a fresh
   `attempt-001` identity. The `scope=observation_manifest` marker prevents using it as
   launch preregistration.
3. Validate an ordered prefix of preparation, generation, execution, scoring, selection,
   and delivery receipts. Reuse the native generation receipt parser and expose only a
   bounded stage projection.
4. Keep primary and joint outcomes at `0/1` until an independent artifact/lifecycle
   inventory and holdout auditor is delivered under a later SDD.
5. Inventory a retained campaign directory as regular-file bytes only, with no-follow descriptor
   access and before/after directory-entry checks. Bind path, size and SHA-256 in a canonical
   digest; audit by recomputing that record without opening databases or executing source.
