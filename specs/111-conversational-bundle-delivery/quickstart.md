# Feature 111 quickstart

Run from the repository root with the project installed in `.venv`:

```sh
.venv/bin/python specs/111-conversational-bundle-delivery/quickstart.py
```

The script creates a temporary input, fixed evaluator profile and local subprocess worker. One
worker serves both normal contract intake and Agent bundle generation. It starts a conversational
`solve --evolve`, generates complete two-file proposals, independently scores them, and delivers
the selected source, output and report to the parent task. It calls ordinary `deliver` and `status`,
then resumes without `--evolve`, checking that no compiler, Agent or candidate runs again and that
only one portable delivery copy exists. All fixture files remain on disk for inspection.

For an existing profile and runtime, the user-facing commands are:

```sh
lunar-evolution solve 'Optimize the supplied data and deliver a working project' \
  --evolve --bundle-profile profile.json --input ./data.csv=data.csv \
  --runtime openai-compatible --endpoint YOUR_ENDPOINT --model YOUR_MODEL --agent-loop \
  --workspace ./mission --json
lunar-evolution solve --resume --run-id RUN_ID --bundle-profile profile.json \
  --runtime openai-compatible --endpoint YOUR_ENDPOINT --model YOUR_MODEL --agent-loop --json
lunar-evolution deliver RUN_ID --json
```

The remote command is a usage template, not part of validation. Supply credentials through the
existing runtime environment configuration. `resume RUN_ID --bundle-profile ...` uses the same
continuation path. If intake asks a question, use `answer RUN_ID 'answer text' --bundle-profile ...`
with the same runtime settings.

Profile input target `data.csv` must match the registered parent input `data/raw/data.csv` by size
and SHA-256. Repeat `--input` for every profile input; undeclared or missing ledger entries are
rejected. Source locations can differ, but the entire declared input set and semantic settings
must match. The effective pipeline uses parent-staged bytes. Profile loading still validates its
original input/harness locations, so preserve those resources for continuation or provide an
equivalent profile pointing to matching copies. Profileless recovery and automatic evaluator
preparation are not implemented.

Parent `output/` files contain the selected evaluation-time snapshot. The complete portable package
is retained under `mission/.bundle-deliveries/`; the solve JSON exposes its relative path and digest
in `evolution.materialization`. The normal `deliver` command verifies it against the original child
evidence and output journal. Independent `candidate-bundle inspect-delivery PATH --delivery-sha256
SHA --json` can inspect a portable copy without the original task Store.

The compiled contract must declare at least one output, preserving the existing bundle evaluation
protocol. Optional outputs may be absent when the independent evaluator accepts that result.
This mode requires native population and does not support `--detach`, `--compile-evaluator`, an
additional `--evaluator-command` or an OpenEvolve producer. Parent output files retain the existing
256 KiB per-file limit, and the full package plus published outputs count toward the parent's
artifact budget. The fixture makes no model/network calls and does not measure real-model quality
or authenticate host dependencies.

Validated on 2026-09-16: four helper-only variants received independent scores `1, 2, 6, 7`.
The parent delivered the 7-point output and complete source/report. Compiler, Agent and candidate
calls remained `1 / 4 / 4` before and after terminal resume, with exactly one delivery copy.
