# `pert.weekly.period_lock.v1`

This pure contract freezes the producer's original weekly period and source
snapshot for retry/rerun validation. It is not an Actions artifact acquisition
implementation and does not read the wall clock.

- `period_start` is a Monday; `period_end_exclusive` is the next Monday;
  `as_of` is the preceding Sunday.
- `source_attempt` is exactly `1`, identifying the original dispatch evidence.
  A retry/rerun compares its expected lock to that original value and never
  derives a new period from `run_attempt` or current time.
- `producer_ref`, source snapshot id/digest/provenance, and canonical sorted
  source artifact path/sha256/row-count entries are part of the lock.
- `generated_at` is intentionally absent: a later producer build may use a new
  actual UTC build timestamp without changing period or source identity.
- Wire is exact/canonical JSON with duplicate-key rejection and stable sanitized
  errors. Unknown, missing, noncanonical, unsafe integer, invalid UTC-week,
  tampered, or source-snapshot-mismatched values fail closed.

The next integration slice must acquire the original lock and immutable input
snapshot before invoking the producer. Missing evidence must not fall back to
wall-clock derivation.
