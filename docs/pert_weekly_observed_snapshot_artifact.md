# PERT weekly observed snapshot artifact

This producer-only slice records a configured-source observed snapshot. It does
not claim global coverage, historical completeness, provider freshness, or
production trust. The existing Saturday RSS/live workflow is unchanged.

- One Monday scheduled/manual run captures one explicit UTC `retrieved_at`.
- `run_attempt` must be exactly 1. Recovery is a new run and source identity;
  reruns and arbitrary historical periods are rejected.
- The same fetched body snapshot generates H2C status, the period projection,
  period lock, manifest, and readback.
- `provider_freshness` is fixed to `unverified`; no provider-date parser is
  implemented in this slice. The artifact is private research evidence only.
- A recognized zero-entry feed is H2C quarantine and prevents a successful
  artifact. Accepted feeds with zero selected rows in the locked period are a
  legal no-event projection and are not stale.
- Missing event dates fail closed; the parser never substitutes `now()`.
- Successful output contains exactly `period_lock.json`, `political_events.csv`,
  `political_watchlist.csv`, `political_event_weekly.json`, and
  `weekly_manifest.json`. The manifest binds run/source identity, retrieved
  time, feed body digests, H2C status, selected count and exact CSV digest.
- Upload retention is 30 days. No QAR consumer, Pages, publisher, legacy live
  path, permission expansion, new data source, or persistent store is included.
