# PoliticalEventTrackingResearch

[English](README.md) | [简体中文](README.zh-CN.md)

Research-only political event and public disclosure tracking for US equities.

This repository asks whether public disclosure, official remarks, policy capital,
procurement, and other public events can be tracked in a repeatable,
point-in-time way.

## Repository Role

This is a deterministic research artifact repository. It does not place trades,
store broker credentials, scrape private accounts, call AI models, or own live
allocation policy.

The stable release scope is:

- collect public disclosure, official remark, policy funding, issuer release,
  financial-media lead, and market reaction events into a consistent CSV schema
- build a candidate tracker from watchlists and event timelines
- run small event studies against local daily close price files
- preserve source links and confidence levels for later manual review

Out of scope for this release:

- X / Twitter ingestion
- Truth Social ingestion
- Longbridge community, profile, or following-list ingestion
- logged-in browser scraping or cookie-based collectors

## Current Status

The committed CSV files under `examples/` are synthetic schema fixtures only.
They are not investment evidence and are not derived from any article.

Tracked event families:

- `disclosure_buy`: public financial disclosure or transaction filing
- `public_mention`: official remarks, issuer statements, or media leads
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

Normalize official, issuer, and media-lead records into the event schema:

```bash
python scripts/import_source_events.py \
  --input examples/official_records.example.csv \
  --output data/output/official_events.example.csv
```

Extract mention events from raw official remarks / RSS / financial-media exports:

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

`.github/workflows/rss_source_pipeline.yml` fetches configured RSS/Atom feeds,
extracts mentions, builds a tracker, and uploads the results as an artifact.

`.github/workflows/source_event_pipeline.yml` runs the same extraction for an
operator-provided `source_items.csv` and uploads `source_events.csv` plus
`source_tracker.csv` as a GitHub Actions artifact. It is intentionally
artifact-only and does not publish recommendations.

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

1. Add more templates for official filings, official remarks, issuer releases,
   government procurement, and financial-media leads.
2. Add source adapters for OGE disclosure PDFs or normalized public datasets.
3. Add public-remarks ingestion from stable government or issuer pages.
4. Backfill enough point-in-time events to evaluate hit rate, lag, and false
   positives before considering any downstream strategy contract.

## Cross-Sector Source Principle

Stable source ingestion is not limited to AI.  Semiconductors, data-center power,
cybersecurity, defense, energy, financials, healthcare, consumer platforms,
industrials, and EV/auto themes can all enter the same `source_items.csv` /
`source_events.csv` structure when durable primary sources exist.

Theme membership and long-horizon semantic bias belong in
`AiLongHorizonSignalPipelines`; this repository only preserves point-in-time
factual evidence so the source boundary is not changed just because a symbol is
currently popular.
