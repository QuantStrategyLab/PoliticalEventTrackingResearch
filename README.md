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

1. Add official-source extraction.
2. Add a source adapter for OGE disclosure PDFs or normalized public datasets.
3. Add public-remarks ingestion from White House pages and social-media exports.
4. Backfill enough point-in-time events to evaluate hit rate, lag, and false
   positives before considering any downstream strategy contract.
