# Trusted workflow identity raw-byte contract

This fresh A0 replacement is pure and does not use Python object identity,
singleton state, capability objects, registries, workflows, permissions,
Actions, bundles, or artifact access as a trust boundary.

## Fixed identity

The only accepted constants are:

- repository: `QuantStrategyLab/PoliticalEventTrackingResearch`
- workflow path: `.github/workflows/pert_weekly_period_lock_harness.yml`
- workflow ref: `QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/pert_weekly_period_lock_harness.yml@refs/heads/main`

`build_trusted_workflow_identity_bytes(reviewed_workflow_sha)` builds canonical
bytes from those module-private constants and an explicitly validated lowercase
40-hex runtime SHA. `validate_trusted_workflow_ref()` accepts only the fixed
workflow ref.

## Operation boundary

`validate_trusted_workflow_identity_bytes(raw)` bounds, parses, shape-checks,
reconstructs, canonicalizes, and compares the complete wire object on every
call. It returns only a plain reviewed-SHA value; the value is not authority
and must not be cached as a capability. Any later operation must retain and
revalidate the original canonical bytes.

The serializer accepts only a `Mapping`, snapshots all entries, validates exact
keys and string types before canonical JSON serialization, and never reads
attributes from arbitrary objects. Duplicate, unknown, missing, noncanonical,
oversized, Unicode/control, wrong identity, and malformed SHA inputs fail with
sanitized `TrustedWorkflowIdentityError` codes. Expected contract exceptions are
sanitized; programming/system exceptions are not broadly caught.

The later A1 bundle integration may consume this raw contract and bind it to
the period lock/snapshot/manifest. It remains blocked until this foundation is
accepted and merged; no workflow or privileged permission is part of A0.
