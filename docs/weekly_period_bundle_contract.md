# `pert.weekly.period_bundle.v1`

This is a pure contract library for a later trusted Actions acquisition
harness. It performs no filesystem, GitHub API, upload, download, or producer
work. The existing `pert.weekly.period_lock.v1` remains the period source of
truth.

## Immutable models

- `BundleContext` fixes the original `run_id`, `source_attempt=1`, exact
  reviewed workflow SHA, producer SHA, expected period lock, and external
  artifact evidence (`name`, `id`, digest, retention).
- `BundleWire` contains only canonical `period_lock.json`,
  `input_snapshot.json`, and `bundle_manifest.json` bytes plus the external
  artifact evidence. Its SHA-256 properties cover all three byte members.
- `RerunContext` accepts only current `run_attempt=2` and reuses the original
  context; it requires the same `run_id`, repository, and reviewed workflow
  SHA as the original context and cannot derive a new period or snapshot.

The repository is an explicit `owner/name` binding in the manifest. Untrusted
bundle members are bounded before parsing: lock 64 KiB, snapshot 256 KiB,
manifest 64 KiB, snapshot depth 16, object keys 64, list items 256, strings
4096 characters, and source artifacts 64. Exceeding any bound fails closed.

The canonical manifest binds the bundle version, artifact name, original run
identity, workflow and producer SHAs, lock/snapshot versions, and exact lock
and snapshot hashes. Artifact id/digest/retention are external Actions
evidence and are required to match the immutable `BundleContext`; manifest
self-hashing is intentionally avoided.

## Verification rules

`verify_period_bundle()` reconstructs the expected lock, snapshot, and manifest
from the complete context and requires byte-for-byte equality. It does not
accept a manifest recomputed from a replacement lock or snapshot. Duplicate,
unknown, missing, reordered, malformed, noncanonical, unsafe-integer, wrong
run/attempt/SHA/artifact, and tampered values fail closed with sanitized
`WeeklyBundleError` codes. `verify_bundle_collection()` requires exactly one
bundle. Unexpected programming/system exceptions are not broad-caught.

This library is PR-1A only. A privileged workflow that has `actions:read` must
be a later PR sourced from the trusted default branch and must never execute
PR-controlled code.
