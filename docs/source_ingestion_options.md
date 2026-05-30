# Source Ingestion Options

## Summary

The preferred ingestion path is:

```text
RSS/API/export/scrape
  -> source_items.csv
  -> extract_source_mentions.py
  -> source_events.csv
  -> tracker/advisory report
```

## Recommended Sources

| Source family | Current option | Confidence | Notes |
| --- | --- | --- | --- |
| White House presidential actions | RSS: `https://www.whitehouse.gov/presidential-actions/feed/` | high | Confirmed RSS response during setup. Some briefing-room category `/feed/` URLs returned 404 and should not be assumed stable. |
| SEC releases/materials | Official RSS page and current press release feed | high | SEC documents RSS availability for press releases, speeches/statements, litigation releases, EDGAR searches, and more. The currently working press feed observed here is `https://www.sec.gov/news/pressreleases.rss`. |
| X | Official X API recent search / full archive / filtered stream | medium | No RSS assumption. Use API if credentials and budget are acceptable. Recent Search covers the last 7 days; full archive needs paid/enterprise access. |
| Truth Social | Raw export or compliant scraper into `source_items.csv` | medium | No stable official RSS/API was confirmed. Treat third-party RSS services as operational dependencies, not primary evidence. |
| Financial media | RSS/API/vendor feed into `source_items.csv` | low | Use as lead only. Upgrade after matching primary social, official remarks, issuer release, or filing. |

## Implementation Notes

- `scripts/fetch_rss_sources.py` fetches RSS/Atom feeds into `source_items.csv`.
- `scripts/fetch_x_recent_search.py` fetches X API v2 Recent Search into
  `source_items.csv`. It requires `X_BEARER_TOKEN`.
- `scripts/import_truthsocial_export.py` converts manually or compliantly
  exported Truth Social JSON into `source_items.csv`.
- `scripts/extract_source_mentions.py` converts `source_items.csv` into normalized event rows by deterministic alias matching.
- `scripts/import_source_events.py` remains available when upstream records are already normalized.

## Operational Caveats

- RSS feeds can lag, change URL paths, or expose partial content only.
- X API access and pricing can change; keep this as an adapter, not a hard dependency.
- Truth Social third-party feeds should be treated as fragile until a stable primary interface is available.
- Media leads must stay low confidence until independently verified.
