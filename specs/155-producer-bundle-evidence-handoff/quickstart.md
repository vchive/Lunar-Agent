```python
from lunar_evolution import build_producer_bundle_publication_artifact

# `archive` is a read-only native CandidateArchive and `candidate` is an existing
# MultiFileCandidatePipeline result with verified cleanup evidence.
artifact = build_producer_bundle_publication_artifact(archive, candidate)
# Pass the artifact to Feature 153 stage_producer_bundle_publication(...).
```

The helper reads retained evidence only. It does not invoke candidate code or an evaluator.
