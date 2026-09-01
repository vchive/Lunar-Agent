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

## Subprocess protocol

The initial subprocess adapter sends the task prompt as UTF-8 on stdin, sets the run workspace as the
working directory, and treats stdout as the result text. The configured command is explicit (for
example, `FAMOU_RUNTIME_COMMAND='my-agent --json'`); the adapter never searches PATH for Hermes or
reads `~/.hermes`.

- Exit code `0`: candidate result returned.
- Non-zero exit code: structured runtime failure with stderr captured in the task log.
- Timeout: process is terminated and the attempt is recorded as failed.
- Empty stdout: failure unless the evaluator explicitly accepts an empty result.

## CLI contract

```text
python -m famou run "<goal>" [--runtime mock|subprocess] [--home PATH]
python -m famou resume <run-id> [--home PATH]
python -m famou status <run-id> [--home PATH]
python -m famou events <run-id> [--home PATH]
python -m famou cancel <run-id> [--home PATH]
```

Commands return zero only when the requested operation succeeds. Status and events are human-readable
by default and may later gain a JSON output flag without changing the state model.
