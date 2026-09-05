# Implementation Plan

1. Add a pure aggregation helper in `deep_effect_trial.py` over validated logical records.
2. Include the helper output in `_case_report` while preserving existing score and baseline fields.
3. Add unit coverage for timeout, run failure, round category, and empty-round accounting.
4. Run focused and repository validation commands.
