# Bounded observed weekly artifact

This is a producer-only private research artifact. It declares a bounded
observation of the configured feeds, not complete weekly or global coverage.

- `coverage_completeness=bounded_unverified`
- `max_items_per_feed=50`
- `truncation_possible=true`
- `private_research_only=true`
- `provider_freshness=unverified`
- `run_attempt=1`; recovery is a new dispatch/run and source identity
- artifact name `political-event-weekly-v1`, retention `30d`

The successful artifact contains exactly:

1. `period_lock.json`
2. `political_events.csv`
3. `political_watchlist.csv`
4. `political_event_weekly.json`
5. `weekly_manifest.json`

`weekly_manifest.json` is canonical JSON and binds the other four member
digests/lengths/row counts, period/as_of, retrieved/generated timestamps,
producer/workflow/run identity, input snapshot identities, H2C status digest,
feed body digests, observed counts, selected-period count and selected CSV
digest. The manifest does not self-hash; its own canonical bytes are validated
by readback.

Event dates use a closed namespace contract:

- RSS `pubDate` is unqualified and timezone-qualified RSS date syntax;
- Atom `published`/`updated` are accepted only in the standard Atom namespace
  and must be timezone-qualified RFC3339;
- Dublin Core `date` is accepted only in the standard Dublin Core namespace
  and must be timezone-qualified RFC3339.

No local-name wildcard is used for event-date fields. Missing/invalid dates
never fall back to the wall clock. RSS structural container compatibility is
separate from date-field namespace validation.

All configured feeds must be H2C `accepted`. A recognized zero-entry feed is
quarantined and prevents a successful artifact. Accepted feeds with zero rows
inside the locked period are a legal no-event projection, provided the emitted
events CSV is exact header-only and its count/digest match the manifest.

This workflow does not modify the Saturday/live pipeline and does not provide
QAR, Pages, publisher, release, migration, or production trust integration.
