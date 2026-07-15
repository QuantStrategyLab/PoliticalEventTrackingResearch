# Weekly period-lock acquisition preflight

This isolated workflow is a test-only proof of same-run GitHub Actions artifact
acquisition. It is not the RSS/source production pipeline and does not publish
producer output.

- Attempt 1 builds one deterministic representative `pert.weekly.period_lock.v1`
  lock and one immutable input snapshot. The period and snapshot are fixed
  fixture values; no wall-clock fallback is allowed.
- The artifact name is `pert-weekly-period-lock-<run_id>`, and the bundle has
  exactly `period_lock.json`, `input_snapshot.json`, and `bundle_manifest.json`.
  The manifest binds the name, original run id, source attempt `1`, and each
  member digest. Retention is 30 days and overwrite is not used.
- Attempt 2 is only the same run's controlled rerun. It downloads that exact
  artifact using the same `github.run_id`, then verifies canonical bytes,
  source run/attempt, artifact name, snapshot identity, member set, and all
  digests. It never derives a new period or uploads a replacement.

The workflow has no contents write, secrets, or OIDC permission. `actions:read`
is used for the readback path and `artifact-metadata:write` is retained for the
artifact upload boundary. This preflight must fail closed if the original-run
artifact is missing, duplicated, replaced, or cannot be read with the declared
permissions.
