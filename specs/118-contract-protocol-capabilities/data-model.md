# Data and compatibility

ConstraintSpec gains optional `verification_scope`:

| Value | Evidence required | Generated bundle support |
| --- | --- | --- |
| `output` | Declared input and output contents | Existing compiler/auditor probes |
| `source` | Delivered source structure | Unsupported; no generated evaluator call |
| `execution` | Program behavior or runtime dependencies | Unsupported; no generated evaluator call |
| Absent | Historical contract's existing interpretation | Unchanged; full hard-constraint coverage |

An explicitly present null is invalid. Omission stays omitted on serialization, so historical
canonical contract bytes and digests remain stable. An explicit output declaration is part of the
new contract identity and cannot be inserted into an old frozen bundle without a digest mismatch.
Hard and soft constraints both preserve their scopes. Strength (`independent`, `partial`, `solver`)
and result_fields do not decide scope or waive coverage. This declaration does not verify the
semantic accuracy of a free-text constraint classification.

`UnsupportedEvaluatorConstraintsError` carries an immutable tuple of `(id, scope)` and returns
a fresh list of `{id, verification_scope}` descriptors from `details()`. Its diagnostics contain
validated contract identifiers and fixed enum values, never provider response text.

Automatic preparation uses its existing start/failure attempt ID. A capability failure adds:

```json
{
  "stage": "capability_check",
  "error_category": "unsupported_verification",
  "recoverable": false,
  "unsupported_constraints": [{"id": "two_files", "verification_scope": "source"}]
}
```

Status validates those descriptors against the retained current contract. A mismatched or malformed
descriptor is reported as validation_error without copying its content. Cancellation takes
precedence. Ordinary earlier preparation observations retain their exact shape. CLI adds a fixed
capability explanation but no retry hint. Explicit resume can record another local failure attempt;
it does not compile a new contract/evaluator or start a candidate.
