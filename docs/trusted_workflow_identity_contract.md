# Trusted weekly workflow identity v1

This is a pure PR-A0 foundation. It performs no filesystem, GitHub Actions,
artifact, workflow, producer, or rerun operation.

## Fixed identity

The only supported identity is compiled into the module:

- repository: `QuantStrategyLab/PoliticalEventTrackingResearch`
- workflow path: `.github/workflows/pert_weekly_period_lock_harness.yml`
- workflow ref: `QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/pert_weekly_period_lock_harness.yml@refs/heads/main`

`trusted_workflow_identity()` is the zero-override API. Callers cannot provide
another repository, path, branch, tag, or ref as a trust root. The reviewed
workflow SHA is separate runtime evidence: it must be exactly 40 lowercase hex
characters and is bound to the fixed identity by
`validate_trusted_workflow_identity()`.

The workflow path is a planned dedicated trusted harness path. This PR does not
create or modify that workflow and does not grant Actions permissions.

## Wire contract

The canonical `pert.trusted_workflow_identity.v1` wire object has exactly:

```json
{"identity_version":"pert.trusted_workflow_identity.v1","repository":"QuantStrategyLab/PoliticalEventTrackingResearch","reviewed_workflow_sha":"<40 lowercase hex>","workflow_path":".github/workflows/pert_weekly_period_lock_harness.yml","workflow_ref":"QuantStrategyLab/PoliticalEventTrackingResearch/.github/workflows/pert_weekly_period_lock_harness.yml@refs/heads/main"}
```

Unknown, missing, duplicate, noncanonical, Unicode/control, alias, wrong
repository/path/ref, and malformed SHA values fail closed with sanitized
`TrustedWorkflowIdentityError` codes. The parser and serializer use the same
fixed identity; they do not accept legacy or future versions.

## Next boundary

The later bundle integration must derive repository/path/ref from this typed
identity, validate `period_lock.workflow_ref` against it, and parse a manifest
structurally before comparing reconstructed canonical bytes. A privileged
workflow and `actions:read` remain outside PR-A0.
