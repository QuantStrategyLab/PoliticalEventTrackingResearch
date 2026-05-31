# Source Ingestion Options

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
