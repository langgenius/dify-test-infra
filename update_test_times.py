"""Publish mean file timings from successful CI on recently merged Dify PRs.

Artifacts are parsed as data only. The source checkout is never downloaded or
executed. GitHub CLI handles authentication and signed artifact redirects.
"""

import argparse
import io
import json
import math
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

SOURCE = "langgenius/dify"
MAX_BYTES = 2 * 1024 * 1024


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{SOURCE}/{path}"]))


def read_observation(archive, shard):
    if len(archive) > MAX_BYTES:
        raise ValueError("Timing archive is too large")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        entries = bundle.infolist()
        if len(entries) != 1 or entries[0].filename != f"durations-{shard}.json":
            raise ValueError("Unexpected timing archive contents")
        if entries[0].file_size > MAX_BYTES:
            raise ValueError("Timing data is too large")
        data = json.loads(bundle.read(entries[0]))
    if not isinstance(data, dict) or not data:
        raise ValueError("Expected a nonempty file duration mapping")
    for name, seconds in data.items():
        if not name.startswith("api/") or not name.endswith(".py") or ".." in name.split("/"):
            raise ValueError("Invalid test file path")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid duration")
    return data


def complete_timing_artifacts(artifacts):
    """Require the declared shard set, while accepting legacy two-shard runs."""
    selected = {}
    for artifact in artifacts:
        name = artifact["name"]
        if name.startswith("api-unit-durations-"):
            if name not in selected or artifact["id"] > selected[name]["id"]:
                selected[name] = artifact
    layouts = set()
    shards = {}
    for name, artifact in selected.items():
        match = re.fullmatch(r"api-unit-durations-([1-9][0-9]*)(?:-of-([1-9][0-9]*))?", name)
        if match is None or artifact["expired"]:
            return None
        index, declared_total = match.groups()
        total = int(declared_total) if declared_total else 2
        layouts.add((declared_total is not None, total))
        shards[int(index)] = artifact
    # Mixed layouts/counts cannot be a complete observation from one workflow.
    if len(layouts) != 1:
        return None
    _, total = layouts.pop()
    if len(shards) != total or sorted(shards) != list(range(1, total + 1)):
        return None
    return sorted(shards.items())


def run_observation(run_id):
    artifacts = api(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    complete = complete_timing_artifacts(artifacts)
    if complete is None:
        return None
    combined = {}
    for shard, artifact in complete:
        archive = subprocess.check_output(["gh", "api", f"repos/{SOURCE}/actions/artifacts/{artifact['id']}/zip"])
        for name, seconds in read_observation(archive, shard).items():
            combined[name] = combined.get(name, 0.0) + seconds
    return combined


def pr_sample(pr):
    """Prefer tested merged code, falling back to the PR head for other merge modes."""
    sources = (("merge_group", pr["merge_commit_sha"]), ("pull_request", pr["head"]["sha"]))
    for event, sha in sources:
        if not sha:
            continue
        query = urlencode({"head_sha": sha, "status": "success", "event": event, "per_page": 10})
        runs = api(f"actions/workflows/main-ci.yml/runs?{query}")["workflow_runs"]
        for run in sorted(runs, key=lambda run: run["run_started_at"], reverse=True):
            observation = run_observation(run["id"])
            if observation is not None:
                return ({
                    "pull_request": pr["number"], "merged_at": pr["merged_at"],
                    "run_id": run["id"], "head_sha": run["head_sha"],
                    "event": event, "run_started_at": run["run_started_at"],
                }, observation)
    return None


def recent_samples(limit=5):
    prs = api("pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100")
    merged = sorted((pr for pr in prs if pr["merged_at"]), key=lambda pr: pr["merged_at"], reverse=True)
    samples = []
    seen_runs = set()
    for pr in merged:
        sample = pr_sample(pr)
        if sample is None or sample[0]["run_id"] in seen_runs:
            continue
        seen_runs.add(sample[0]["run_id"])
        samples.append(sample)
        if len(samples) == limit:
            break
    # A recently merged PR may have run CI days ago. File discovery must follow
    # the newest observed checkout, not the order in which PRs happened to merge.
    return sorted(samples, key=lambda sample: sample[0]["run_started_at"], reverse=True)


def average_samples(samples):
    """Use the latest sample's file set so removed files do not accumulate."""
    if not samples:
        return {}
    result = {}
    for name in samples[0][1]:
        values = [data[name] for _, data in samples if name in data]
        result[name] = sum(values) / len(values)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--verify-run", type=int, help="Check artifact access without publishing an unmerged run")
    args = parser.parse_args()
    if args.verify_run:
        run = api(f"actions/runs/{args.verify_run}")
        if run["conclusion"] != "success":
            raise ValueError("Verification requires a successful run")
        observation = run_observation(args.verify_run)
        if observation is None:
            raise ValueError("Run has no complete timing observations")
        print(f"Verified cross-repository artifact access: {len(observation)} files from run {args.verify_run}")
        return
    samples = recent_samples()
    if not samples:
        print("No complete observations from merged PRs; keeping the existing baseline")
        return
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "test-times.json").write_text(json.dumps(average_samples(samples), indent=2, sort_keys=True) + "\n")
    metadata = {
        "schema": 1, "source_repository": SOURCE, "platform": "Linux", "python": "3.12",
        "metric": "summed testcase setup/call/teardown seconds", "aggregation": "mean of up to 5 recent merged PRs",
        "updated_at": datetime.now(timezone.utc).isoformat(), "samples": [metadata for metadata, _ in samples],
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(f"Prepared {len(samples)} samples for publication")


if __name__ == "__main__":
    main()
