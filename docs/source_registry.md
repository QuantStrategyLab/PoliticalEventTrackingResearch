# Source Registry

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
- U.S. Treasury press releases and RSS feed:
  <https://home.treasury.gov/news/press-releases>
  <https://home.treasury.gov/rss/press-releases.xml>
- Federal Reserve press releases, speeches, testimony, and RSS feeds:
  <https://www.federalreserve.gov/newsevents/pressreleases.htm>
  <https://www.federalreserve.gov/feeds/feeds.htm>
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
`AiLongHorizonSignalPipelines`.  This repository only emits point-in-time source
items and events with URLs, dates, source type, and confidence.  A source item
must not be promoted just because a theme or symbol is popular in the current
market.
