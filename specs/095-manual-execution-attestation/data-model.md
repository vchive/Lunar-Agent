# Data model

Attestation schema 1 keys: parent_run_id, evolution_run_id, task_id, launch_intent_sha256,
candidate_id, candidate_sha256, attempt_path, execution_path, execution_sha256, execution_size,
device, inode, nonce. The nonce is 32–128 safe characters. A single
`materialization_execution_attested` event stores the fixed identity and receipt digest; no new
artifact table or execution schema is introduced.
