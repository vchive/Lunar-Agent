# Feature 125: Compiler self-tests pass; independent audit prevents freeze

The single new diagnostic ended with **freeze0/1 and joint success0/1**. Both model requests
returned successfully. Native compiler parsing, source validation and self-tests completed, so the
controller issued the independent auditor request. Local preparation then raised EvaluatorBundleError
before freeze. **Zero of eight registered holdouts executed.** No solver, candidate or delivery ran.

## Registration and scope

Registration `ef29c36c0868b57489af1c16c095bdb2fb133676` was pushed before launch. The local remote
ref's update-by-push record is06:44:26UTC; the new campaign started06:44:51.015273UTC.
Product remains `eefe389d14c2380ceb7db9089636f6a5ebe15e2a` without edits. Manifest SHA256:
`c76a7f4802ad2691fc0c400c3525f9e38f4c520399a1a6a9f8f8e4506ea43a12`.

This is a separate denominator of one, with the complete123 contract/input/profile/eight holdouts,
provider metadata, native sampling omissions and budgets preserved. The retained problem_id ends
in123 intentionally; the root/slot belongs only to125. Only campaign identity, product commit and
compiler request differ among the prior fixed fields. There was no retry, resume, fallback,
replacement, manual auditor call or execution of the old123 generated source.

## Observed results

| Stage | Result | Request duration | Known tokens |
| --- | --- | --- | --- |
| Compiler | HTTP200; native self-tests accepted, auditor subsequently called | 326.682s | 28538 (3724 input +24814 output) |
| Auditor | HTTP200; subsequent local preparation failed | 50.640s | 7961 (4345 input +3616 output) |
| Freeze | None,0/1 | — | — |
| Holdouts | 0 executed of8 planned | — | — |

Total known usage is complete: **36499 tokens =8069 input+28430 output**. Cost is unknown;
quality and gap are null. Supervisor duration378.853s, exit1, process_status=exited;
cleanup_verified=true and remaining observed PIDs=[]; worker stage=preparation and
error_class=EvaluatorBundleError. Worker elapsed378.647s. These are not successful delivery scores.

Compiler/auditor requests are16751/19504 bytes. Both were independently reconstructed offline
from fixed prompt builders and captured compiler objective/source, matching ledger and transport:

- Compiler SHA `ed75c5972decd24dff57bbdc47f4e92e0ea96ab7a811bb1c8acc9e7efa52e56f`, also the preregistered hash.
- Auditor SHA `dff8d47a9af546fbd6ac5cc79d53f5d33eff0caaffba9193a1e6116bf435fe32`.

Both retained transport rows contain HTTP200 and last_milestone=response_headers_received,
http_exchange_index=1,elapsed_ms326518/50596. Whole exchange observations are326681/50639ms.
These observations do not split connect/write/header wait or establish provider compute/queue time.
Raw HTTP bodies were not retained; only lengths103816/15181 bytes and recorded hashes are available.

## Static explanation of the rejected evaluator

After the slot finished, pure native parsing accepted the compiler envelope/source and its three
probes, and the auditor's five probes. Both assistant captures are complete, untruncated and
unredacted, with exact size/hash verification against the published evidence inventory.

The compiler source correctly uses an input descriptor's target and an output descriptor's path.
However, it interprets the entire parsed JSON input as the integer limit. All three compiler
self-probe input files also contain a scalar JSON integer. The contract and actual registered input
instead require an object with an integer limit field; the structural profile exposes that field.
All five auditor inputs have this correct object shape, including four expected-valid probes.

Static AST inspection identifies the branch: the JSON reader returns the whole root at source
lines6–8; line21 assigns that root as the limit; line38 rejects a non-int root and line39 adds an
error. Lines52–53 emit an invalid report when errors exist, with validity0,qualitynull,score0.
There is no limit field lookup in the source. A correctly shaped first valid auditor input is
therefore rejected by this branch. This is a sufficient static defect, **not a replay of the
original runtime traceback**, which was not retained. Generated code/probes/holdouts were not
re-executed after the attempt, and no response was repaired.

The independent auditor supplied a distinguishing case and the controller prevented freeze.
This is not an auditor failure established by the evidence. Compiler self-tests alone did not
detect their shared wrong input representation. Current preflight explicitly validates output
schema but does not enforce declared semantic input structure on synthetic input bytes.

## Evidence and limits

All16 retained files match the inventory by size/SHA. Inventory SHA256:
`1e0b9ea9e8551af1458419244b30d3e879476082f3a008ccf94eb73f9cf73121`.
The77product/14measurement/91history pins and all10 frozen implementation/test hashes match.
Private captures stay in the local campaign root; only metadata and static findings are published.

| Capture | Parsed text bytes / SHA256 | Private capture file bytes / SHA256 |
| --- | --- | --- |
| Compiler | 3958 / `7e0af00ecd962dd1472f62ef4663e40597512aecc7fdacb0094e597cb8142e11` | 4513 / `98d22c0e8f84501a2dc1a3b9baceadaefa1abf6c69ecba4869e88e1e7bf88c7d` |
| Auditor | 1120 / `efd9f335ad2aeb34b810f16aff8a28b232e5e2224d4acf0af393226a68076da3` | 1654 / `df7dcfe97c175d2b8130c7a0868346d2d976a3d58e79bc20b769b106b3db2c8b` |

The earlier123 remains0/1;113/115/117/120 remain separately0/2. This run progressed through native
compiler acceptance, but one uncontrolled sample does not establish that124 caused improvement or
that latency improved. It does not diagnose old120 timeouts, prove evaluator correctness or validate
real multi-file delivery. Integer-only holdouts were unrun and never establish general type coverage.

Next work should address consistency between declared input structure and synthetic compiler probes,
starting with the existing real-input format rules: the profile parser accepts JSON objects or
arrays of objects and already rejects scalar JSON roots. Reuse those bounded parsing rules for
synthetic probe inputs instead of inventing a schema from prose field descriptions or treating
observed counts/types as universal task constraints. Also preserve a precise local failure stage
for future diagnosis. Keep independent audit and the
strict freeze boundary; do not treat these compiler self-tests as successful evaluator preparation.

Machine-readable artifacts: [results](results.json), [evidence inventory](evidence.json),
[static diagnosis](static-response.json). The [static inspector](inspect_responses.py) checks the
fixed manifest, registered bytes and full inventory before parsing; it never executes generated code.
