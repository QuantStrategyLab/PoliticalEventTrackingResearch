# PoliticalEventTrackingResearch

<!-- qsl-doc-overview:start -->

> ⚠️ 投资有风险，不构成投资建议，仅供学习交流用途。
> ⚠️ Investing involves risk. This project does not provide investment advice and is for educational and research purposes only.

## Open-source overview / 开源项目入口

| Item | Description |
| --- | --- |
| Project type | research pipeline |
| What it does | Tracks public political/policy event evidence and transforms it into auditable source items/events for research. |
| 中文说明 | 公开政治/政策事件研究管线，产出可审计 source_items/source_events，不做 AI 决策或交易执行。 |
| Current status | Research-only evidence pipeline. |

### Quick start

- `python -m pip install -e '.[test]'`
- `python -m pytest -q`

### Deploy / operate safely

Run source collection and publication workflows only after checking rate limits, source terms and output paths.

### Strategy performance / evidence boundary

The research plan covers post-event 1/5/20 trading-day returns and benchmark-relative analysis; see `docs/research_plan.zh-CN.md`.

> Detailed runbooks, migration notes, workflow internals, and historical decisions are kept below. Start with this overview before using the lower-level operational sections.

<!-- qsl-doc-overview:end -->

> ⚠️ 投资有风险，不构成投资建议，仅供学习交流用途。


## 中文摘要

- 完整中文版见 [`README.zh-CN.md`](README.zh-CN.md)；本节保留在英文文件顶部，方便从当前文件直接找到中文入口。
- 用途：本文档围绕 `PoliticalEventTrackingResearch`，用于理解 `PoliticalEventTrackingResearch` 的配置、运行、部署、研究或验收边界。
- 主要覆盖：`Repository Role`、`Current Status`、`Local Validation`、`Data Contracts`、`Live Pipeline Notes`。
- 阅读顺序：先确认边界、输入输出和权限要求，再执行文档里的命令、CI、dry-run、发布或切换步骤。
- 风险提示：涉及实盘、密钥、权限、Cloud Run、交易所或券商 API 的变更，必须先在测试环境或 dry-run 验证；不要只凭示例直接修改生产。
- 英文正文保留更完整的命令、字段名和配置键；如果摘要和正文不一致，以正文中的实际命令和配置为准。
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
extracts mentions, builds a tracker, and uploads the results as an artifact. On
scheduled runs it also commits public live CSV outputs under `data/live/`:

```text
data/live/source_items.csv
data/live/source_events.csv
data/live/political_events.csv
data/live/source_tracker.csv
data/live/source_fetch_status.json
data/live/source_manifest.json
```

`data/live/political_events.csv` is the stable input consumed by
`QuantAdvisorResearch`. This repository still only publishes source evidence; it
does not generate investment recommendations.

`.github/workflows/source_event_pipeline.yml` runs the same extraction for an
operator-provided `source_items.csv`. Scheduled runs use `data/live/source_items.csv`
after the RSS pipeline and can refresh `data/live/source_events.csv`,
`data/live/political_events.csv`, and `data/live/source_tracker.csv`.

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

## Live Pipeline Notes

The RSS fetcher records per-feed health in `data/live/source_fetch_status.json` and keeps a small hash/row-count plus data-quality manifest in `data/live/source_manifest.json`. The manifest summarizes feed health, covered symbols, confidence counts, and event-type counts. A single blocked or unavailable feed should not stop the rest of the official-source refresh.

If the RSS workflow downloads articles but `source_events.csv` is empty, the
usual cause is deterministic alias coverage rather than a fetch failure: broad
policy items often mention sectors such as grid infrastructure, HBM, foundry,
AI servers, or crypto assets instead of company names. Alias updates should
remain targeted, documented, and reviewable to avoid turning every broad policy
article into a false positive.

Local macOS Python installations can also fail HTTPS RSS fetches with a local CA
certificate error. GitHub-hosted runners use a normal CA bundle; local operators
can either repair the Python certificate store or validate extraction from a
downloaded `source_items.csv` artifact.

## Short-Horizon Event Boundary

This repository is the short-horizon event evidence layer for Advisor `1-10 trading days` catalyst checks. It emits source URLs, dates, event types, and confidence only. It does not directly produce short-term buy/sell recommendations; final short/medium/long recommendations remain in `QuantAdvisorResearch`.

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
- AI-generated shadow signals; those belong in `ResearchSignalContextPipelines`
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
`ResearchSignalContextPipelines`; this repository only preserves point-in-time
factual evidence so the source boundary is not changed just because a symbol is
currently popular.
