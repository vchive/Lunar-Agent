# Plan

Clone Feature 129's reviewed measurement harness into a new campaign-local package. Keep its task,
worker, observation, supervision and read-only analyzer behavior unchanged except for module and
campaign identity. Point the product pin at Feature 130, retain seed 129, and add explicit immutable
references to both Feature 128 preparation and Feature 129's previous attempt.

Run the copied offline fixtures under Feature 131 names. Add registration checks for product commit,
new root, both historical manifest hashes, unchanged task/provider/budget/population conditions,
once-only launch, committed bytes and pushed `origin/main`. Include Features 129 and 130 in the
historical file inventory.

After relevant regression, Feature 112 recovery, static checks and independent review pass, create
the manifest, verify it, commit and push the registration. Confirm `HEAD == origin/main` and the new
campaign root is absent. Then run the sole attempt and summarize once. Independently audit the
retained evidence, update the report, validation, roadmap and handoff, then commit and push results.
