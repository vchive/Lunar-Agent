# Data model

Bundle keys: `schema_version`, `parent_run_id`, `evolution_run_id`, `report`, `events`, `artifacts`.
Events and artifacts contain only fixed identity, type/kind and byte size/digest metadata. The
report is schema 1 from 093 and always has `recovery_eligibility: not_assessed`.
