# Trusted weekly period bundle A1

This is a pure integration of the merged raw identity contract. It performs no
filesystem, workflow, permissions, Actions, artifact acquisition, upload,
download, rerun, producer, QAR, Pages, legacy, or migration operation.

## Boundary

`build_period_bundle()` and `verify_period_bundle()` accept bounded canonical
raw bytes and plain mappings only. Every call reparses and validates the lock,
source snapshot, trusted identity bytes, manifest, and artifact evidence. No
Python object identity, frozen dataclass, singleton, capability, or registry is
trusted.

The manifest is independently parsed first. Its exact key set, duplicate keys,
types, canonical bytes, fixed repository/workflow path/ref, runtime reviewed
SHA, run/attempt, artifact metadata, and lock/snapshot hashes are checked before
reconstructed expected bytes are compared.

## Full binding

The bundle binds:

- canonical `pert.weekly.period_lock.v1` bytes and SHA-256;
- canonical `pert.weekly.input_snapshot.v1` bytes and source metadata;
- fixed `pert.trusted_workflow_identity.v1` repository/path/ref and explicit
  reviewed workflow SHA;
- original source run id and attempt 1;
- artifact name, id, digest, and retention;
- canonical manifest bytes and all reconstructed expected values.

Replacement, tampering, missing/unknown/duplicate/noncanonical data, malformed
mapping objects, unsafe integers, oversized/deep snapshot data, wrong identity,
or artifact mismatch fail closed with sanitized `TrustedPeriodBundleError`
codes. Expected contract exceptions are sanitized; system/programming
exceptions are not broadly caught.

The next privileged workflow integration remains a separate step and must use
trusted default-branch code. It is not part of A1.
