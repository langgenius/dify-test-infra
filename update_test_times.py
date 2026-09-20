"""Publish mean file timings from successful CI on recently merged Dify PRs.

Artifacts are parsed as data only. The source checkout is never downloaded or
executed. GitHub CLI handles authentication and signed artifact redirects.
"""

import argparse
import io
import json
import math
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


def run_observation(run_id):
    artifacts = api(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    selected = {}
    for artifact in artifacts:
        if not artifact["expired"]:
            name = artifact["name"]
            if name not in selected or artifact["id"] > selected[name]["id"]:
                selected[name] = artifact
    if any(f"api-unit-durations-{shard}" not in selected for shard in (1, 2)):
        return None
    combined = {}
    for shard in (1, 2):
        artifact = selected[f"api-unit-durations-{shard}"]
        archive = subprocess.check_output(["gh", "api", f"repos/{SOURCE}/actions/artifacts/{artifact['id']}/zip"])
        for name, seconds in read_observation(archive, shard).items():
            combined[name] = combined.get(name, 0.0) + seconds
    return combined


def recent_samples(limit=5):
    prs = api("pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100")
    merged = sorted((pr for pr in prs if pr["merged_at"]), key=lambda pr: pr["merged_at"], reverse=True)
    samples = []
    for pr in merged:
        query = urlencode({"head_sha": pr["head"]["sha"], "status": "success", "event": "pull_request", "per_page": 10})
        runs = api(f"actions/workflows/main-ci.yml/runs?{query}")["workflow_runs"]
        for run in runs:
            observation = run_observation(run["id"])
            if observation is not None:
                samples.append(({
                    "pull_request": pr["number"], "merged_at": pr["merged_at"],
                    "run_id": run["id"], "head_sha": run["head_sha"],
                }, observation))
                break
        if len(samples) == limit:
            break
    return samples


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
