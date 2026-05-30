# Source Registry

This file records source families for future ingestion. A source listed here is
not automatically trusted; every event still carries its own `source_url` and
`confidence`.

## Seed Source

- Longbridge topic 41260998:
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

## Confidence Guide

- `high`: official source or direct filing with stable URL.
- `medium`: reputable secondary source with enough details to locate official
  source later.
- `low`: article, community post, or manually transcribed lead pending review.

