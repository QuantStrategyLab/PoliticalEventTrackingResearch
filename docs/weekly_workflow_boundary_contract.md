# Weekly Workflow Boundary Contract

The RSS workflow validates dispatch identity before fetching, writing `data/live`,
committing, or uploading artifacts.

- Manual runs require an exact completed ISO week: Monday `period_start` and
  Sunday `as_of`.
- Scheduled runs fetch the current run from GitHub's workflow-run REST endpoint
  using `actions:read`. The response must match the fixed repository, workflow
  path, `refs/heads/main`, `event=schedule`, `run_id`, `run_attempt=1`, and a
  full producer SHA. The immutable API `created_at` date determines the previous
  complete UTC ISO week; runner `date -u` is not period authority.
- The existing `rss-source-pipeline` upload occurs before dedicated weekly build.
  A weekly contract failure leaves that legacy/source artifact available while
  still failing the workflow and preventing dedicated upload.
- Dedicated `political-event-weekly-v1` remains the exact five-file, 30-day,
  complete-feed, digest-bound artifact defined by `weekly_artifact.py`.

No new secrets, id-token, external store, identity registry, consumer, Pages,
publisher, or trading capability is introduced.
