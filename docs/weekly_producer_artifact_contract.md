# Political Event Weekly Producer Artifact

`political-event-weekly-v1` is the producer-owned, complete-UTC-ISO-week artifact
emitted by the RSS source pipeline.

## Fixed contract

- Scheduled execution is Monday `12:15 UTC` and covers the immediately preceding
  complete Monday–Sunday UTC ISO week.
- Manual execution must provide matching `period_start` (Monday) and `as_of`
  (Sunday). No latest-source or wall-clock fallback is allowed for period identity.
- `generated_at` is the actual UTC build time and is separate from period identity.
- `GITHUB_RUN_ATTEMPT` must be exactly `1`; a rerun is fail-closed rather than a
  new version of the same snapshot.
- Artifact retention is exactly 30 days.

The dedicated artifact contains exactly:

```text
period_lock.json
political_events.csv
political_watchlist.csv
political_event_weekly.json
weekly_manifest.json
```

The manifest binds the first four files by name, byte length and SHA-256. It also
records CSV headers/row counts, period/as-of/generated-at, producer SHA,
workflow ref, run id/attempt, source snapshot digest/provenance, and complete
feed counters. Any partial/failed/stale/missing feed, source mismatch, unsafe
wire, or readback mismatch prevents dedicated artifact upload.

This contract is producer-side only. QAR consumer acquisition/readback is a
separate later slice; no legacy compatibility, identity store, Pages, publisher,
or workflow permission expansion is implied.
