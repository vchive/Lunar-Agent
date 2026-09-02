# Data Model: Evolution Adapter Provenance

No database migration is required. The fields live in the existing JSON strategy state/config.

`EvolutionConfig` gains two optional fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `generator_fingerprint` | `string \| null` | SHA-256 of the explicit generator/solver command and profile |
| `evaluator_fingerprint` | `string \| null` | SHA-256 of the explicit evaluator command and profile |

When unset, the corresponding key is omitted from `to_dict()` for compatibility with callback-only
callers and state written before this feature. Fingerprints are lowercase 64-character SHA-256
hex strings and contain no raw command or prompt data.
