# Weekly producer artifact contract

This is the producer-side boundary for `political_event_weekly.v1`. It is a
pure local adapter: callers provide the completed UTC week, `as_of`, actual
UTC `generated_at`, producer full SHA, provenance identifier, input files, and
feed status. The adapter never infers dates, reads the wall clock, fetches
feeds, or uploads files.

## Artifact

- Name: `political-event-weekly-v1`
- File set: exactly `weekly_manifest.json`
- Retention: 30 days, configured by the consuming artifact workflow; it is not
  inferred from report content.
- Bytes: canonical `political_event_weekly.v1` manifest bytes from the merged
  weekly manifest serializer.

The input file paths are repository-relative POSIX paths under the trusted
`base_dir`. They must be regular, non-symlink files. Their SHA-256 and CSV row
counts are read from those exact files. The feed status file must be one of
the declared inputs, and its counters must agree with every feed entry. Any
failed, stale, missing, partial, malformed, or mismatched input fails before
the output directory is created.

The CLI requires all period, timestamp, producer, provenance, and path inputs
explicitly. Upload availability is an external workflow gate: callers must
only upload the returned artifact after successful local readback; an upload
step that cannot accept the exact single-file artifact must fail the workflow,
not publish a success signal.

The RSS source workflow now supplies this boundary without changing fetching:
scheduled runs execute Monday UTC after the previous ISO week is complete and
derive that week using the documented producer rule; manual runs require both
`period_start` and `as_of`. It uploads the single manifest with a 30-day
retention setting. Other workflows and downstream consumers are unchanged.
