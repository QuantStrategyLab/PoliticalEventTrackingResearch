# Free data source setup

[简体中文](free_source_setup.zh-CN.md)

## Shipped files

- `config/free_rss_feeds.csv`: official RSS feeds that need no account.
- `config/core_us_equity_aliases.csv`: core US equity watchlist aliases.
- `data/live/political_watchlist.csv`: initial watchlist for the live publish path.
- `data/live/source_items.csv`: latest raw text pulled by the scheduled RSS pipeline.
- `data/live/source_events.csv`: events extracted deterministically from `source_items.csv`.

`source_events.csv` keeps the original columns and adds the following compatible
evidence columns: `entity_match_type`, `match_evidence`, and
`relationship_type`. Values are `issuer`, `direct_beneficiary`,
`industry_context`, or `unverified`. Only the first two are company-level
evidence; industry vocabulary is retained for auditability but is not scored as
an issuer event. Rows without a verifiable entity match are not emitted by the
live extractor. Legacy imported rows default to `unverified` and therefore fail
closed in downstream company-event scoring.

Historical event-study compatibility is opt-in only. Use
`--historical-compatibility --compatibility-reason "..."` for a pre-schema CSV.
Rows remain `unverified`; output records include `compatibility_used`,
`compatibility_reason`, and `legacy_provenance`.
- `data/live/political_events.csv`: stable Advisor input, refreshed by RSS/source pipeline or maintained after manual review.
- `data/live/source_tracker.csv`: merged watchlist and event tracker.

See the Chinese setup note for cron wiring, refresh commands, and operator checks.
