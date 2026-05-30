# PoliticalEventTrackingResearch

[English](README.md) | [简体中文](README.zh-CN.md)

Research-only political event and public disclosure tracking for US equities.

This repository asks whether public disclosure, official remarks, policy capital,
procurement, and other political/public events can be tracked in a repeatable,
point-in-time way.

## Repository Role

This is a deterministic research artifact repository. It does not place trades,
store broker credentials, scrape private accounts, call AI models, or own live
allocation policy.

The initial research scope is:

- collect public disclosure, public remark, policy funding, and market reaction
  events into a consistent CSV schema
- build a candidate tracker from watchlists and event timelines
- run small event studies against local daily close price files
- preserve source links and confidence levels for later manual review

## Current Status

The committed CSV files under `examples/` are synthetic schema fixtures only.
They are not investment evidence and are not derived from any article.

Tracked event families:

- `disclosure_buy`: public financial disclosure or transaction filing
- `public_mention`: White House, speech, interview, social-media, or media
  mention
- `policy_capital`: government capital, procurement, or industrial-policy
  support
- `market_reaction`: earnings, contract, analyst, or price reaction marker

## Local Validation

Build the seed tracker:

```bash
python scripts/build_tracker.py \
  --watchlist examples/political_watchlist.example.csv \
  --events examples/political_events.example.csv \
  --output data/output/political_tracker.example.csv
```

Normalize official, primary social, and media-lead records into the event schema:

```bash
python scripts/import_source_events.py \
  --input examples/official_records.example.csv \
  --output data/output/official_events.example.csv
```

Extract mention events from raw Truth Social / X / official remarks /
financial-media exports:

```bash
python scripts/extract_source_mentions.py \
  --raw-items examples/source_items.example.csv \
  --aliases examples/symbol_aliases.example.csv \
  --output data/output/source_events.example.csv
```

Fetch RSS/Atom sources into the same raw item schema:

```bash
python scripts/fetch_rss_sources.py \
  --feeds examples/rss_feeds.example.csv \
  --output data/output/rss_source_items.example.csv \
  --max-items-per-feed 10
```

See `docs/source_ingestion_options.md` for RSS/API/scraping tradeoffs. See
`docs/longbridge_community_ingestion.zh-CN.md` for Longbridge community lead
ingestion.

`.github/workflows/rss_source_pipeline.yml` fetches configured RSS/Atom feeds,
extracts mentions, builds a tracker, and uploads the results as an artifact.

Fetch X recent-search results when `X_BEARER_TOKEN` is available:

```bash
X_BEARER_TOKEN=... python scripts/fetch_x_recent_search.py \
  --queries examples/x_queries.example.csv \
  --output data/output/x_source_items.example.csv
```

Convert a Truth Social JSON export into `source_items.csv`:

```bash
python scripts/import_truthsocial_export.py \
  --input examples/truthsocial_export.example.json \
  --output data/output/truthsocial_source_items.example.csv
```

Optionally try the public Truth Social endpoint manually:

```bash
python scripts/fetch_truthsocial_public.py \
  --username realDonaldTrump \
  --output data/output/truthsocial_source_items.csv \
  --limit 20
```

Convert Longbridge community topic JSON into low-confidence research leads:

```bash
python scripts/import_longbridge_topics.py \
  --input examples/longbridge_topics.example.json \
  --author-allowlist examples/longbridge_followed_authors.example.csv \
  --output data/output/longbridge_source_items.example.csv
```

If the official Longbridge CLI is installed and authenticated, fetch configured
keyword searches directly:

```bash
python scripts/fetch_longbridge_cli_topics.py \
  --keywords config/longbridge_topic_keywords.csv \
  --include-details \
  --raw-output data/output/longbridge_topics.raw.json \
  --source-items-output data/output/longbridge_source_items.csv \
  --author-allowlist data/live/longbridge_followed_authors.csv
```

`.github/workflows/source_event_pipeline.yml` runs the same extraction and
uploads `source_events.csv` plus `source_tracker.csv` as a GitHub Actions
artifact. It is intentionally artifact-only and does not publish recommendations.

Free-source setup notes are in
[`docs/free_source_setup.zh-CN.md`](docs/free_source_setup.zh-CN.md).

Run the synthetic event study:

```bash
python scripts/run_event_study.py \
  --events examples/political_events.example.csv \
  --prices examples/price_history.example.csv \
  --windows 1,2 \
  --output data/output/event_study.example.csv
```

Run tests:

```bash
python -m pytest -q
```

## Data Contracts

Event input schema:

```text
event_id,event_date,symbol,event_type,direction,confidence,source_url,notes
```

Watchlist input schema:

```text
symbol,name,bucket,research_status,thesis,source_url
```

Price input schema:

```text
date,symbol,close
```

The price loader also accepts `as_of` instead of `date`.

## Boundary

This repo owns:

- research schemas for political/disclosure/mention event tracking
- seed watchlists and event timelines
- deterministic event-study utilities over local daily prices
- source registry and promotion notes

This repo does not own:

- broker API access or order placement
- Telegram or runtime notifications
- paid market-data redistribution
- legal claims about conflicts of interest
- AI-generated shadow signals; those belong in `AiLongHorizonSignalPipelines`
- live strategy promotion into `UsEquityStrategies` or broker platforms

## Next Work

1. Add more source adapters and record templates for official filings, official
   remarks, verified Truth Social / X posts, and financial-media leads.
2. Add a source adapter for OGE disclosure PDFs or normalized public datasets.
3. Add public-remarks ingestion from White House pages and social-media exports.
4. Backfill enough point-in-time events to evaluate hit rate, lag, and false
   positives before considering any downstream strategy contract.
