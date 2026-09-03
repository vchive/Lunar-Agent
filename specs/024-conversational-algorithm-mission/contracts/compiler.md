# Contract: `ContractCompiler`

```python
class ContractCompiler(Protocol):
    def compile(
        self, goal: str, workspace: Path, *, answer: str | None = None,
        timeout: float | None = None,
    ) -> CompilationResult: ...
```

`CompilationResult.status` is `compiled` or `needs_input`. A compiled result contains a validated
`AlgorithmProblemContract`; an awaiting result contains one to four bounded questions. Any runtime,
JSON, schema, secret, or size error raises `ContractCompilationError` and must fail closed.
