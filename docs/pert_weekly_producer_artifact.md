# PERT weekly producer artifact

This is a producer-only, configured-source observed snapshot. It is not a claim
of global coverage and it does not implement historical backfill. The existing
Saturday RSS/live workflow is unchanged.

## Contract

- The dedicated workflow runs Monday at `12:45 UTC` and permits only
  `run_attempt == 1`. A rerun is rejected; recovery is a new run with a new
  source identity.
- At job start one UTC reference time is captured. It determines the immediately
  prior completed ISO week: Monday `period_start`, exclusive next Monday
  `period_end_exclusive`, and Sunday `as_of`. Manual inputs are accepted only
  when they exactly match that derived period. No wall-clock fallback is used
  for a manual period and no historical period is inferred.
- Each configured feed is fetched once. The same parsed snapshot produces the
  canonical H2C status, period-filtered event CSV, period lock, and manifest.
  Any failed, stale, missing, or quarantined feed prevents a successful weekly
  artifact. A recognized zero-entry feed remains quarantine/non-eligible.
- A successful artifact contains exactly these five files:
  `period_lock.json`, `political_events.csv`, `political_watchlist.csv`,
  `political_event_weekly.json`, and `weekly_manifest.json`.
  The manifest records canonical names, SHA-256 digests, row counts, period,
  `as_of`, `generated_at`, producer/workflow/run identity, feed completeness,
  and `retention_days=30` is applied by the workflow upload step.
- The artifact is read back locally before upload. File-set, regular-file,
  canonical JSON, period-lock, H2C status, manifest, digest, and contract
  checks fail closed. The artifact name is `political-event-weekly-v1`.

The H2C status proves that the configured feeds were accepted in the single
fetch snapshot. `political_events.csv` is the deterministic projection of that
same snapshot restricted to the locked week; it does not re-fetch or re-parse
the source. This distinction keeps feed completeness and period event
selection explicit.

This slice does not publish to QAR, Pages, a publisher, or the legacy live
path, and it does not add a persistent identity/store or new permission.
