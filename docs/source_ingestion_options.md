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
| Truth Social | Public endpoint attempt, raw export, or compliant scraper into `source_items.csv` | medium | Public endpoint access can be blocked by Cloudflare and should be treated as best-effort. Keep raw export/import as the stable fallback. |
| Longbridge community | Official OpenAPI/CLI topic list/detail export into `source_items.csv` | low | Useful for high-quality community lead discovery. Followed-author collection requires a user-maintained author allowlist unless Longbridge exposes a followed-feed endpoint. |
| Financial media | RSS/API/vendor feed into `source_items.csv` | low | Use as lead only. Upgrade after matching primary social, official remarks, issuer release, or filing. |

## Implementation Notes

- `scripts/fetch_rss_sources.py` fetches RSS/Atom feeds into `source_items.csv`.
- `scripts/fetch_x_recent_search.py` fetches X API v2 Recent Search into
  `source_items.csv`. It requires `X_BEARER_TOKEN`.
- `scripts/import_truthsocial_export.py` converts manually or compliantly
  exported Truth Social JSON into `source_items.csv`.
- `scripts/fetch_truthsocial_public.py` tries the public Truth Social account
  endpoints into `source_items.csv`; use it manually because public access may
  be blocked or changed.
- `scripts/import_longbridge_topics.py` converts Longbridge topic list/detail
  JSON into `source_items.csv`. Use `--author-allowlist` to keep only followed
  high-quality community authors.
- `scripts/fetch_longbridge_cli_topics.py` optionally calls the official
  Longbridge CLI for configured symbols, writes raw topic JSON, and can produce
  `source_items.csv` in one step. It requires the CLI to be installed and
  authenticated outside this repository.
- `scripts/extract_source_mentions.py` converts `source_items.csv` into normalized event rows by deterministic alias matching.
- `scripts/import_source_events.py` remains available when upstream records are already normalized.

## Operational Caveats

- RSS feeds can lag, change URL paths, or expose partial content only.
- X API access and pricing can change; keep this as an adapter, not a hard dependency.
- Truth Social public endpoint and third-party feeds should be treated as fragile until a stable primary interface is available.
- Longbridge community leads are not official facts. Keep them as low-confidence `community_research_lead` rows unless a primary source confirms the claim.
- Media leads must stay low confidence until independently verified.
