# Source Ingestion Options


## 中文摘要

- 用途：本文档围绕 `Source Ingestion Options`，用于理解 `PoliticalEventTrackingResearch` 的配置、运行、部署、研究或验收边界。
- 主要覆盖：`Summary`、`Stable Sources`、`Deferred Sources`、`Implementation Notes`、`Operational Caveats`。
- 阅读顺序：先确认边界、输入输出和权限要求，再执行文档里的命令、CI、dry-run、发布或切换步骤。
- 风险提示：涉及实盘、密钥、权限、Cloud Run、交易所或券商 API 的变更，必须先在测试环境或 dry-run 验证；不要只凭示例直接修改生产。
- 英文正文保留更完整的命令、字段名和配置键；如果摘要和正文不一致，以正文中的实际命令和配置为准。

## Summary

The stable ingestion path is:

```text
RSS/API/export
  -> source_items.csv
  -> extract_source_mentions.py
  -> source_events.csv
  -> tracker/advisory report
```

## Stable Sources

| Source family | Current option | Confidence | Notes |
| --- | --- | --- | --- |
| White House presidential actions | RSS: `https://www.whitehouse.gov/presidential-actions/feed/` | high | Some briefing-room category `/feed/` URLs may be unstable; keep feed URLs explicit in config. |
| SEC releases/materials | Official RSS page and press release feed | high | SEC documents RSS availability for press releases, speeches/statements, litigation releases, EDGAR searches, and more. |
| Federal Reserve | Official press release, speech, and testimony RSS | high | Used for monetary policy and financial-system context. |
| NIST / CISA | Official RSS feeds in `config/free_rss_feeds.csv` | high | Adds technology standards, cybersecurity, and energy coverage without login. |
| FTC | Candidate RSS/page source | high | FTC feeds returned 403 to the current Python fetcher during verification, so they are documented but not enabled by default. |
| Federal Register / USAspending | Future API adapters or operator-provided CSV export | high | Public APIs are good candidates for later stable adapters. |
| Issuer releases | Operator-provided CSV or future RSS/API adapter | medium | Use direct issuer/IR URLs. |
| Financial media | RSS/API/vendor feed into `source_items.csv` | low | Use as lead only. Upgrade after matching official, filing, or issuer material. |

## Deferred Sources

X / Twitter, Truth Social, and Longbridge community/following-list ingestion are
not part of this release. Reasons:

- API access, pricing, or anti-bot behavior can change.
- Login-state or cookie-based collection is operationally fragile.
- Community/social posts are research leads, not primary evidence.

## Implementation Notes

- `scripts/fetch_rss_sources.py` fetches RSS/Atom feeds into `source_items.csv`.
- `scripts/extract_source_mentions.py` converts `source_items.csv` into normalized event rows by deterministic alias matching.
- `scripts/import_source_events.py` remains available when upstream records are already normalized.
- `scripts/write_live_manifest.py` records hash, row-count, feed-health, covered-symbol, confidence, and event-type summaries for live artifacts.

## Operational Caveats

- RSS feeds can lag, change URL paths, or expose partial content only.
- Media leads must stay low confidence until independently verified.
- Do not store credentials, cookies, or private account data in this repository.
