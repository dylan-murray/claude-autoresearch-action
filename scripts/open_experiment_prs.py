#!/usr/bin/env python3
"""Open one PR per goal that produced kept commits on its experiment branch.

Called by the open-prs job in .github/workflows/claude-autoresearch.yml. The
PR body contains the holistic verdict + metric trajectory + iteration log
summary so a human reviewer has everything they need in one place. PRs are
not auto-merged; the human decides.

Reads (from --artifacts-dir):
  loop-<goal_id>/goal.json        — goal definition
  loop-<goal_id>/baseline.json    — starting metric value
  loop-<goal_id>/best.json        — final best metric
  loop-<goal_id>/iteration-log.jsonl — per-iter status (kept/reverted/etc.)
  verdict-<goal_id>/holistic-verdict.json — judge's end-of-loop assessment

Env vars:
  RUN_ID    — pipeline run id (used to construct branch names)
  GH_TOKEN  — for `gh pr create`

Skips goals with no `kept` iterations (empty diff = no useful PR to open).
Logs failures (e.g., PR already exists) without failing the run.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys


def load_json(path: str, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def count_kept(log_path: str) -> int:
    if not os.path.isfile(log_path):
        return 0
    n = 0
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("status") == "kept":
                    n += 1
    except OSError:
        pass
    return n


def iteration_log_summary(log_path: str) -> str:
    """Render a compact one-line-per-iteration summary for the PR body."""
    if not os.path.isfile(log_path):
        return "_(no iteration log)_"
    lines: list[str] = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                status = e.get("status", "?")
                emoji = {
                    "kept": "✓",
                    "reverted": "✗",
                    "guard_failed": "🛡️",
                    "metric_error": "⚠️",
                    "no_op": "·",
                    "error": "💥",
                }.get(status, "?")
                metric = e.get("metric")
                metric_str = f"`{metric}`" if metric is not None else "—"
                what = e.get("what", "")
                iter_n = e.get("iter", "?")
                lines.append(
                    f"- iter {iter_n} {emoji} `{status}` — metric {metric_str} — {what}"
                )
    except OSError:
        return "_(could not read log)_"
    return "\n".join(lines) if lines else "_(empty log)_"


def build_pr_body(*, goal: dict, verdict: dict, baseline: dict, best: dict, log_path: str) -> str:
    title = goal.get("title", goal.get("id", "?"))
    direction = goal.get("direction", "?")
    rationale = goal.get("rationale", "")
    metric_baseline = baseline.get("value")
    metric_final = best.get("value")
    set_at_iter = best.get("set_at_iter")

    if verdict:
        rating = verdict.get("rating", "?")
        confidence = verdict.get("confidence", "?")
        summary = verdict.get("summary", "")
        wins = verdict.get("key_wins") or []
        concerns = verdict.get("key_concerns") or []
        metric_validity = verdict.get("metric_validity", "?")
        iteration_pattern = verdict.get("iteration_pattern", "?")
        recommendation = verdict.get("recommendation", "?")
    else:
        rating = "—"
        confidence = "—"
        summary = "_(no holistic verdict produced — judge step may have failed)_"
        wins = []
        concerns = []
        metric_validity = "—"
        iteration_pattern = "—"
        recommendation = "—"

    wins_block = "\n".join(f"- {w}" for w in wins) or "_(none stated)_"
    concerns_block = "\n".join(f"- {c}" for c in concerns) or "_(none stated)_"

    return f"""## Experiment: {title}

> {rationale}

### Mechanical result
- **Direction:** {direction}
- **Baseline:** `{metric_baseline}`
- **Final:** `{metric_final}` (best set at iter {set_at_iter})

### Holistic verdict — `{rating}` (confidence {confidence})

> {summary}

**Key wins:**
{wins_block}

**Key concerns:**
{concerns_block}

| | |
|---|---|
| Metric validity | {metric_validity} |
| Iteration pattern | {iteration_pattern} |
| Recommendation | {recommendation} |

### Iteration log

{iteration_log_summary(log_path)}

---
*Opened by [`claude-autoresearch-action`](https://github.com/dylan-murray/claude-autoresearch-action). The per-iteration metric drove keep/revert decisions; the holistic verdict above is an opus-class second opinion. Review the diff carefully before merging — every commit on this branch was generated by an AI agent.*"""


def open_pr_for_goal(*, run_id: str, goal_id: str, art_dir: str) -> bool:
    """Open one PR for the given goal. Returns True on success, False on skip/fail."""
    loop_dir = os.path.join(art_dir, f"loop-{goal_id}")
    verdict_dir = os.path.join(art_dir, f"verdict-{goal_id}")

    log_path = os.path.join(loop_dir, "iteration-log.jsonl")
    kept = count_kept(log_path)
    if kept == 0:
        print(f"[{goal_id}] no `kept` iterations; skipping PR")
        return False

    goal = load_json(os.path.join(loop_dir, "goal.json"), {}) or {}
    baseline = load_json(os.path.join(loop_dir, "baseline.json"), {}) or {}
    best = load_json(os.path.join(loop_dir, "best.json"), {}) or {}
    verdict = load_json(os.path.join(verdict_dir, "holistic-verdict.json"))

    branch = f"autoresearch/exp/{run_id}/{goal_id}"
    title_text = goal.get("title", goal_id)
    rating = (verdict or {}).get("rating", "no-verdict")
    pr_title = f"autoresearch[{rating}]: {title_text}"
    body = build_pr_body(
        goal=goal, verdict=verdict, baseline=baseline, best=best, log_path=log_path
    )

    cmd = [
        "gh", "pr", "create",
        "--base", "main",
        "--head", branch,
        "--title", pr_title,
        "--label", "autoresearch",
        "--body", body,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        print(f"[{goal_id}] opened PR: {out.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[{goal_id}] failed to open PR: {e.output}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", default=".autoresearch/_artifacts")
    args = parser.parse_args()

    run_id = os.environ.get("RUN_ID", "unknown")

    loop_dirs = sorted(glob.glob(os.path.join(args.artifacts_dir, "loop-*")))
    if not loop_dirs:
        print("No loop artifacts found; nothing to PR")
        return 0

    print(f"Found {len(loop_dirs)} goal(s) for run {run_id}")
    for d in loop_dirs:
        goal_id = os.path.basename(d).removeprefix("loop-")
        open_pr_for_goal(run_id=run_id, goal_id=goal_id, art_dir=args.artifacts_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
