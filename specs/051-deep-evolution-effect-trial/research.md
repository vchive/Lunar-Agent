# Research Notes: Deep-Evolution Effect Trial

- The local WebAgent source was inspected before implementation. Its no-argument evolution command
  initializes five outer iterations; this is distinct from ordinary model/tool turns inside one run.
- Feature 048 intentionally excludes deep evolution and compares only normal runs. Feature 051 keeps
  that baseline and adds a separately named protocol so the two measurements cannot be conflated.
- The evaluator remains the authority. Round feedback is a derived, bounded score summary from the
  just-completed private harness, not a user-entered target or historical baseline value.
- A five-round local loop is effect-layer comparable, not a claim that prompts, role documents,
  service orchestration, or model sampling are byte-identical to WebAgent.
