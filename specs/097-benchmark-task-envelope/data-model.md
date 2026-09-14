# Data model

`BenchmarkTaskEnvelope` is schema `1` with protocol `lunar-benchmark-task-v1`. It contains
`benchmark` and `task` identities, the Lunar contract digest, bounded input file descriptors,
model profile digest, exact evaluator identity, single-file candidate kind, and physical budget.
The canonical envelope digest hashes the complete normalized object. A comparison digest binds the
contract, input manifest, model, evaluator and physical budget while excluding framework scores and
run IDs.

Admission rechecks every referenced input under a caller supplied root and compares all caller pins.
It returns an immutable projection with no source contents. It does not evaluate, execute or write.
