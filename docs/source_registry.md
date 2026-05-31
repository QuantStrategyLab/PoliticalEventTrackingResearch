# Source Registry


## 中文摘要

- 用途：本文档围绕 `Source Registry`，用于理解 `PoliticalEventTrackingResearch` 的配置、运行、部署、研究或验收边界。
- 主要覆盖：`Candidate Official Sources`、`Candidate Issuer Sources`、`Candidate Lead Sources`、`Deferred Sources`、`Current Configured RSS Feeds`。
- 阅读顺序：先确认边界、输入输出和权限要求，再执行文档里的命令、CI、dry-run、发布或切换步骤。
- 风险提示：涉及实盘、密钥、权限、Cloud Run、交易所或券商 API 的变更，必须先在测试环境或 dry-run 验证；不要只凭示例直接修改生产。
- 英文正文保留更完整的命令、字段名和配置键；如果摘要和正文不一致，以正文中的实际命令和配置为准。
This file records source families for the stable research release. A source
listed here is not automatically trusted; every event still carries its own
`source_url` and `confidence`.

## Candidate Official Sources

- U.S. Office of Government Ethics public financial disclosure resources:
  <https://www.oge.gov/web/OGE.nsf/publicresources_FOIA-landing>
- OGE announcement for annual public financial disclosure timing:
  <https://www.oge.gov/web/oge.nsf/Resources/Annual%2BPublic%2BFinancial%2BDisclosure%2BReports%2Bare%2BDue%2Bto%2Bbe%2BFiled%2Bon%2BMay%2B15th>
- Clerk of the U.S. House financial disclosure search:
  <https://disclosures-clerk.house.gov/FinancialDisclosure>
- White House remarks:
  <https://www.whitehouse.gov/remarks/>
- SEC press releases and EDGAR materials:
  <https://www.sec.gov/newsroom/press-releases>
  <https://www.sec.gov/edgar/search/>
- U.S. Treasury press releases page, kept as a candidate HTML source until a stable RSS feed is verified:
  <https://home.treasury.gov/news/press-releases>
- Federal Reserve press releases, speeches, testimony, and RSS feeds:
  <https://www.federalreserve.gov/newsevents/pressreleases.htm>
  <https://www.federalreserve.gov/feeds/feeds.htm>
- NIST news, cybersecurity, and energy RSS feeds:
  <https://www.nist.gov/news-events/news/rss.xml>
  <https://www.nist.gov/news-events/cybersecurity/rss.xml>
  <https://www.nist.gov/news-events/energy/rss.xml>
- CISA news RSS:
  <https://www.cisa.gov/news.xml>
- FTC press release pages and RSS feeds, kept as candidates until feed access is stable from the runner:
  <https://www.ftc.gov/feeds/press-release.xml>
  <https://www.ftc.gov/feeds/press-release-competition.xml>
- Federal Register:
  <https://www.federalregister.gov/>
- USAspending:
  <https://www.usaspending.gov/>

## Candidate Issuer Sources

- Issuer investor-relations pages, SEC filings, and company press releases.
- Use `issuer_release` and keep the direct stable URL in `source_url`.

## Candidate Lead Sources

- Reputable financial media can be used as low-confidence leads only. Leads
  should be upgraded only after matching official filings, official remarks,
  issuer releases, or other primary material.

## Deferred Sources

The stable release intentionally excludes X / Twitter, Truth Social, and
Longbridge community/profile/following-list ingestion. They can be revisited
later only if a stable official interface and clear operating policy exist.

## Current Configured RSS Feeds

`config/free_rss_feeds.csv` keeps the stable default set limited to official
feeds that can be replayed without login:

- White House presidential actions
- SEC press releases
- SEC speeches and statements
- Federal Reserve press releases
- Federal Reserve speeches and testimony
- NIST general, cybersecurity, and energy news
- CISA news

FTC RSS URLs are documented above as candidates, but are not in the default CSV
because the feed returned 403 to the current Python fetcher during verification.

`data/live/source_manifest.json` records source row counts, feed health, covered
symbols, confidence counts, and event-type counts for every published live run.

## Alias Coverage Notes

`config/core_us_equity_aliases.csv` includes targeted aliases for the current AI
and data-center names that often appear through products or infrastructure terms,
including MU, INTC, AMD, DELL, and VRT. Alias updates should prefer company names,
product names, or clear infrastructure phrases over very broad hype terms.

## Confidence Guide

- `high`: official government source or direct filing with stable URL.
- `medium`: issuer release or other primary issuer material.
- `low`: financial-media lead pending primary source review.

## Cross-Sector Coverage Boundary

Stable source coverage should remain cross-sector and should not be limited to AI
or the current market hot list.  The source layer can collect official evidence
for semiconductors, data-center power, cybersecurity, defense, energy,
financials, healthcare, consumer platforms, industrials, crypto infrastructure,
and EV/auto themes when a durable primary source exists.

Theme membership and long-horizon semantic bias are owned by
`ResearchSignalContextPipelines`.  This repository only emits point-in-time source
items and events with URLs, dates, source type, and confidence.  A source item
must not be promoted just because a theme or symbol is popular in the current
market.

## Long-Horizon Evidence Boundary

Long-horizon recommendations in `QuantAdvisorResearch` should not depend on this
repository alone. This repository can improve confidence when durable primary
evidence exists, such as SEC filings, issuer releases, official procurement,
Federal Register notices, agency grants, or official policy documents. If those
events are absent, the Advisor may still rank a symbol through theme context and
momentum; that should be interpreted as low event/news support rather than an
ingestion failure in this repository.
