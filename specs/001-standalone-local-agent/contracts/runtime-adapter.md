# Runtime Adapter Contract

The controller owns task state. A runtime adapter only executes one bounded task and returns a
structured result. Adapter implementations MUST be deterministic about success/failure reporting and
MUST NOT write outside the workspace path supplied by the controller.

## Python contract

```python
class Runtime(Protocol):
    name: str

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        """Execute one task and return text plus optional artifact paths."""

    def cancel(self) -> None:
        """Request cancellation of the active invocation, if any."""

    def set_process_observer(self, observer: Callable[[int, int | None], None] | None) -> None:
        """Observe a spawned process for durable attempt metadata, when supported."""

    def process_info(self) -> tuple[int | None, int | None]:
        """Return local PID/PGID for detached cancellation, or ``(None, None)``."""
```

`RuntimeResult` contains:

```json
{
  "text": "human-readable result",
  "artifacts": ["relative/path.txt"],
  "metadata": {"provider": "mock"}
}
```

The controller validates artifact paths, hashes files, persists the result, and decides whether the
task is verified. A runtime MUST NOT mark a database task successful itself.
When a detached controller is cancelled, a result that arrives after cancellation MUST be discarded
and recorded as `task_result_discarded`, never attached as a successful artifact.

## Subprocess protocol

The initial subprocess adapter sends the task prompt as UTF-8 on stdin, sets the run workspace as the
working directory, and treats stdout as the result text. The configured command is explicit (for
example, `FAMOU_RUNTIME_COMMAND='my-agent --json'`); the adapter never searches PATH for Hermes or
reads `~/.hermes`.

- Exit code `0`: candidate result returned.
- Non-zero exit code: structured runtime failure with stderr captured in the task log.
- Timeout: process is terminated and the attempt is recorded as failed.
- Empty stdout: failure unless the evaluator explicitly accepts an empty result.

## OpenAI-compatible HTTP protocol

The built-in `openai-compatible` adapter sends:

```json
{
  "model": "configured-model",
  "messages": [{"role": "user", "content": "task prompt"}],
  "stream": false
}
```

to the explicitly configured endpoint. It accepts `choices[0].message.content`,
`choices[0].text`, or an Ollama-compatible top-level `message.content`. The endpoint is supplied by
`--endpoint` or `FAMOU_MODEL_ENDPOINT`; the model by `--model` or `FAMOU_MODEL`; an optional API key
comes from `--api-key` or `FAMOU_API_KEY`. Keys are never included in persisted errors or logs.

## CLI contract

```text
python -m famou run "<goal>" [--runtime mock|subprocess] [--home PATH] [--json] [--detach]
python -m famou run [<goal>] --plan PLAN.json [--runtime mock|subprocess] [--home PATH] [--json]
python -m famou run "<goal>" --runtime openai-compatible --endpoint URL --model MODEL [--json]
python -m famou run - [--runtime mock|subprocess] [--home PATH] [--json]  # goal from stdin
python -m famou resume <run-id> [--home PATH] [--json]
python -m famou status <run-id> [--home PATH] [--json]
python -m famou events <run-id> [--home PATH] [--json]
python -m famou cancel <run-id> [--home PATH] [--json]
```

Commands return zero only when the requested operation succeeds. Human-readable output is the
default. With `--json`, stdout contains exactly one JSON value and diagnostics are written to stderr;
this is the stable interface for Codex, Hermes, OpenClaw, shell scripts, or another Agent invoking
Lunar-Agent as a child process. `run --detach --json` persists the run, starts a local background
controller, and returns the run ID before task execution begins; it writes controller output under
the run workspace. A caller must treat the run ID as the durable handle and use `resume`, `status`,
or `cancel` after a timeout or process interruption.
