# Free data source setup

[简体中文](free_source_setup.zh-CN.md)

## Shipped files

- `config/free_rss_feeds.csv`: official RSS feeds that need no account.
- `config/core_us_equity_aliases.csv`: core US equity watchlist aliases.
- `data/live/political_watchlist.csv`: initial watchlist for the live publish path.
- `data/live/source_items.csv`: latest raw text pulled by the scheduled RSS pipeline.
- `data/live/source_events.csv`: events extracted deterministically from `source_items.csv`.
- `data/live/political_events.csv`: stable Advisor input, refreshed by RSS/source pipeline or maintained after manual review.
- `data/live/source_tracker.csv`: merged watchlist and event tracker.

## Entity-field preservation stage

The RSS/source extractor exports the eight existing event columns followed by
`entity_match_type`, `match_evidence`, and `relationship_type`. This stage only
preserves the normalized fields in the CSV; it does not verify company
relationships. Extracted mentions retain `unverified`, an empty evidence string,
and `unverified`, respectively. Source `confidence=high` describes the source
type, not verified company evidence. Generic terms such as "strategy",
"cybersecurity", or "crypto assets", and incidental references to WhatsApp do
not establish an issuer or direct-beneficiary relationship.

With `commit_outputs=true`, the source workflows stage generated live files and
upload a patch plus a `HUMAN_REQUIRED` receipt. An authorized maintainer reviews
the patch and submits it through a normal protected-branch PR; the workflows do
not directly publish to `main`. Preserving these fields does not collect new
evidence, regenerate live data, or change downstream acceptance requirements.
Real company evidence and its data PR remain a separate reviewed step.

See the Chinese setup note for cron wiring, refresh commands, and operator checks.
