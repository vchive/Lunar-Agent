# Implementation plan

1. Keep the observer as a pure parser over in-memory canonical JSON; no provider,
   subprocess, evaluator, Store write, or campaign launch is reachable from its API.
2. Bind a manifest draft to the fixed Feature 142 observation budgets and the `attempt-001`
   format. The `scope=observation_manifest` marker identifies a draft; it is not launch
   preregistration and does not yet establish identity freshness or file/Git pins.
3. Validate an ordered prefix of preparation, generation, execution, scoring, selection,
   and delivery receipts. Reuse the native generation receipt parser and expose only a
   bounded stage projection.
4. Keep primary and joint outcomes at `0/1` until an independent artifact/lifecycle
   inventory and holdout auditor is delivered under a later SDD.
5. Inventory a retained campaign directory as regular-file bytes only, with no-follow descriptor
   access and before/after directory-entry checks. Bind path, size and SHA-256 in a canonical
   digest; audit by recomputing that record without opening databases or executing source.

The inventory uses a second complete metadata scan to revisit files in previously closed
subdirectories. Traversal counts directories as well as files and stops before exceeding its entry
budget. Descriptor cleanup covers errors immediately after open. No SQLite schema, dependency or
recovery-state migration is needed; both APIs recompute observations and do not write evidence.

An alternative that promoted six `succeeded` metadata receipts directly into success was rejected:
the current slice cannot verify their underlying artifact/lifecycle semantics. Feature 148 defines
that next adapter. Constitution II/IV/VI are satisfied by read-only recomputation, bounded artifacts,
and deterministic corruption/interruption fixtures; no governance exception is needed.
