# Source Registry

This file records source families for future ingestion. A source listed here is
not automatically trusted; every event still carries its own `source_url` and
`confidence`.

## Inspiration Sources

- The Longbridge topic below inspired the initial research question. It is not
  committed as an event seed and should not be treated as evidence without
  official-source verification:
  <https://longbridge.com/zh-CN/topics/41260998.md>

## Candidate Official Sources

- U.S. Office of Government Ethics public financial disclosure resources:
  <https://www.oge.gov/web/OGE.nsf/publicresources_FOIA-landing>
- OGE announcement for annual public financial disclosure timing:
  <https://www.oge.gov/web/oge.nsf/Resources/Annual%2BPublic%2BFinancial%2BDisclosure%2BReports%2Bare%2BDue%2Bto%2Bbe%2BFiled%2Bon%2BMay%2B15th>
- Clerk of the U.S. House financial disclosure search:
  <https://disclosures-clerk.house.gov/FinancialDisclosure>
- White House remarks:
  <https://www.whitehouse.gov/remarks/>
- Longbridge Developers documentation:
  <https://open.longbridge.com/docs>

## Candidate Primary Social Sources

- Truth Social posts from the relevant verified/person-owned account:
  <https://truthsocial.com/>
- X posts from the relevant verified/person-owned account:
  <https://x.com/>

## Candidate Lead Sources

- Reputable financial media can be used as low-confidence leads only. Leads
  should be upgraded only after matching official filings, official remarks,
  primary social posts, issuer releases, or other primary material.

## Confidence Guide

- `high`: official source or direct filing with stable URL.
- `medium`: primary social source with a stable, verifiable URL, or issuer
  release.
- `low`: financial-media article or manually transcribed lead pending primary
  source review.
