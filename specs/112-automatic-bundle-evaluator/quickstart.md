# Feature 112 quickstart

From the repository root with the project installed in `.venv`:

```sh
.venv/bin/python specs/112-automatic-bundle-evaluator/quickstart.py
```

The standalone script creates an input and a deterministic local subprocess worker. The worker
serves normal contract intake, evaluator compilation, a separate adversarial audit and complete
two-file candidate generation. Lunar validates the evaluator's compiler probes and independent
audit probes before preparing its own pipeline profile. The script supplies no `--bundle-profile`.

Four helper-only variants receive independent scores `1, 2, 6, 7`; the parent delivers the complete
7-point source, output and report. Ordinary `deliver` and `status` pass. Terminal `solve --resume`
omits all evolution/profile flags and leaves call counts unchanged: contract compiler `1`, evaluator
compiler `1`, auditor `1`, Agent `4`, candidates `4`. Only one portable delivery copy exists.
All fixture files remain in the temporary root printed by the script. Validation uses no model,
network or external evolution framework and does not establish effectiveness on real tasks.

For a configured model endpoint:

```sh
lunar-evolution solve 'Optimize the supplied orders and deliver a working Python project' \
  --evolve --multi-file --input ./orders.csv=orders.csv \
  --runtime openai-compatible --endpoint YOUR_ENDPOINT --model YOUR_MODEL --agent-loop \
  --workspace ./mission --json
lunar-evolution solve --resume --run-id RUN_ID \
  --runtime openai-compatible --endpoint YOUR_ENDPOINT --model YOUR_MODEL --agent-loop --json
lunar-evolution deliver RUN_ID --json
```

The remote example is a usage template, not part of validation. Supply credentials through the
existing runtime environment configuration. If intake asks a question, use `answer RUN_ID 'answer
text'` with the same runtime settings; `resume RUN_ID` also recovers the saved mode. Repeating
`--multi-file` is optional for continuation, and `--compile-evaluator` is redundant in this mode.

Preparation saves `mission/evaluator-bundle/` and `mission/bundle-profile.json`. Resume uses these
retained files and parent-staged inputs; the original source input paths need not remain available.
Changing/removing prepared evaluator, profile or registered input bytes is rejected instead of
asking a model to regenerate the judge. Keep the complete task workspace and Store for recovery.

The compiled contract must declare at least one output, and its input paths must match the complete
registered input set. Automatic preparation supports the existing `csv`, `json`, `jsonl` and `text`
input formats. Probes retain the original 32-file/64 KiB-per-file and 512 KiB aggregate limits;
contracts exceeding those limits can still use a separately prepared explicit bundle profile.
Candidate execution uses local Python without dependency installation. Dependency/environment
digests describe selected configuration and do not authenticate installed packages.

This mode requires native population. External profiles/evaluator commands, OpenEvolve and detached
solving cannot be combined with `--multi-file`. Generated evaluators must pass the required probes,
but that does not prove their full business correctness. Independent audit results and objective
text are retained for review; judge source and probe answers are not staged in solver context.
