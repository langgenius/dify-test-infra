# Dify test infrastructure

Public test timing baselines for `langgenius/dify`, maintained separately so that
statistics do not grow the application repository's Git history.

`generated-stats/stats/test-times.json` maps repository-relative Python test files
to summed setup/call/teardown seconds on Linux / Python 3.12. Dify downloads this
file anonymously and freezes one assignment plan for all CI shards. A missing or
unavailable baseline falls back to round-robin file allocation.

The workflow runs every hour (at minute 05 UTC) and reads the latest 100
updated, closed PRs targeting Dify main, keeps merged PRs, and selects up to five
distinct successful Main CI runs with every required timing artifact unexpired. For each
PR, it prefers a merge-group run whose SHA exactly matches the merged commit,
falling back to the PR head when no complete merge-group observation is available.
This includes the final measurements taken against the merge queue's base without
trusting observations from unmerged queue entries. A run is sampled only once,
even when it is associated with multiple merged PRs.

Samples are ordered by CI start time, not PR merge time. The updater averages
observations per file, retaining the newest observed checkout's file set. Only
merged PRs contribute automatically. Neither source code nor artifact contents
are executed. `metadata.json` records the exact source PRs, events, run times, and
runs. When no observations are available, the existing baseline is preserved.
Artifacts currently expire after seven days.

Timing artifacts declare the shard count as `api-unit-durations-<index>-of-<total>`.
The updater requires every index from 1 through the declared total, rejects mixed
counts or naming formats, and uses the newest artifact for each name. A missing
or expired final shard cannot silently produce a partial baseline. Legacy runs
with exactly `api-unit-durations-1` and `api-unit-durations-2` remain supported.
The JSON member inside each archive stays named `durations-<index>.json`.

The initial baseline is explicitly marked as a bootstrap from validated PR #42593
CI, pending that PR's merge. It will be replaced by merged-PR observations once
available. The updater does not accept arbitrary unmerged PRs for publication.

The updater uses GitHub CLI and Python's standard library. Its workflow token
writes only this repository. To check access to Dify artifacts without publishing,
run the manual workflow with `verify-run` set to a successful Dify CI run ID.

Run tests with `python3 -m unittest discover -s tests -v`.
