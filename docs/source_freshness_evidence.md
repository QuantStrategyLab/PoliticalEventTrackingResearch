# Source freshness evidence v1

This producer-boundary contract records freshness evidence for one bounded feed
response. It does not claim that a feed is globally complete, and it does not
use event `published_at` as a provider freshness signal.

Signal priority is fixed:

1. Atom feed `updated`;
2. RSS channel `lastBuildDate`;
3. HTTP `Last-Modified`.

HTTP `Date` is recorded as retrieval/server-time evidence only and never makes
the source eligible. A present but invalid, future, or stale higher-priority
signal fails closed; fallback is allowed only when that signal is absent. The
selected signal must be no more than five minutes in the future and no older
than eight days relative to the caller-supplied canonical UTC reference.

The evidence is canonical JSON bytes containing only digests for the source URL
identity and response body, all signal presence/value/kind records, the
reference, policy version, and decision. It does not persist the source URL or
request headers. Missing all selectable signals produces
`source_freshness_unverified`. A period projection with zero selected events is
not stale by itself; H2C feed quarantine remains a separate producer result.
