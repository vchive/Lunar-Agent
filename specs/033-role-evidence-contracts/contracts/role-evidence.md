# Role evidence contract v1

The built-in role plan stores these acceptance leaves in its immutable `PlanDocument`:

```json
{
  "data_profile_valid": "data/processed/data-profile.json"
}
```

```json
{
  "artifact_valid": {
    "path": "solve/problem-formulation.md",
    "format": "text",
    "fields": []
  }
}
```

```json
{
  "evaluation_report_valid": "evaluate/evaluation.json"
}
```

`artifact_valid` uses the normal bounded UTF-8 and structured format interpreter. The data profile
requires schema version `1`, at least one `data/raw/...` input observation, a non-negative integer
row count, unique columns, and bounded issue strings. The evaluation report is parsed with
`famou.algorithm.EvaluationReport`; no natural-language claim or `result.txt` can substitute for
the file.
