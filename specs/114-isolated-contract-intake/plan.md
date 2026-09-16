# Plan

Change only the contract compiler dispatch and its schema prompt. Reuse the existing isolated
runtime implementation used by evaluator compilation/auditing; do not introduce another runtime,
relax parsing, strip markdown, guess unknown fields or automatically spend on a repair request.

Use optional capability detection for `run_isolated`, preserving subprocess and custom runtimes
that implement only `run`. A failure from an available isolated path is terminal for that compiler
call. Repository mock behavior remains deterministic. Existing validated contracts, plans and
intake response shapes require no migration; ordinary task execution still uses `run`.
Keep the existing runtime-settings fingerprint: it is not a product-code digest. Previously
compiled/terminal runs reuse their plans without recompilation; an existing `awaiting_input` run
uses the repaired compiler when its next explicit answer arrives. The separate 113 source pins
continue to prohibit treating a run on this implementation as the old measurement.

Focused tests inspect the actual messages and empty tool schema reaching Hermes' model boundary,
not merely a stub method name. Check answer propagation, timeout, no history/memory replay,
strict rejection and one-call behavior. Also exercise subprocess fallback and ordinary tools.
The full regression and Feature 112 local quickstart validate controller/CLI/recovery compatibility.

RuntimeResult metadata is not persisted by the existing CompilationResult path. This feature does
not claim a new product-wide usage ledger; the frozen 113 campaign's known usage came from its
registered complete-call guard. Preserve all 113 registration and postrun bytes. Subsequent real
measurement requires a separate registration pinned to the repaired implementation.
