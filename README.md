# Dify test infrastructure

Public test timing baselines for `langgenius/dify`, maintained separately so that
statistics do not grow the application repository's Git history.

`generated-stats/stats/test-times.json` maps repository-relative Python test files
to summed setup/call/teardown seconds on Linux / Python 3.12. Dify downloads this
file anonymously and freezes one assignment plan for all CI shards. A missing or
unavailable baseline falls back to round-robin file allocation.

The daily workflow (03:05 UTC) reads the latest 100 updated, closed PRs targeting
Dify main, keeps merged PRs, and selects up to five with successful Main CI runs
and both unexpired timing artifacts. It averages observations per file, retaining
the newest sample's file set. Only merged PRs contribute automatically. Neither
source code nor artifact contents are executed. `metadata.json` records the exact
source PRs and runs. When no observations are available, the existing baseline is
preserved. Artifacts currently expire after seven days.

The initial baseline is explicitly marked as a bootstrap from validated PR #42593
CI, pending that PR's merge. It will be replaced by merged-PR observations once
available. The updater does not accept arbitrary unmerged PRs for publication.

The updater uses GitHub CLI and Python's standard library. Its workflow token
writes only this repository. To check access to Dify artifacts without publishing,
run the manual workflow with `verify-run` set to a successful Dify CI run ID.

Run tests with `python3 -m unittest discover -s tests -v`.
