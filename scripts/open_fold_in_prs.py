#!/usr/bin/env python3
"""Open fold-in PRs from per-goal verdict artifacts.

Called by the fold-in job in .github/workflows/claude-autoresearch.yml.

Reads:
  .autoresearch/_artifacts/verdict-<goal_id>/holistic-verdict.json   (one per goal)
  .autoresearch/_artifacts/loop-<goal_id>/best.json                  (final metric)
  .autoresearch/_artifacts/loop-<goal_id>/baseline.json              (starting metric)
  .autoresearch/_artifacts/loop-<goal_id>/goal.json                  (goal definition)

Env vars:
  RUN_ID         — pipeline run id (for context only)
  FOLD_IN_MODE   — `all_above_threshold` | `best` | `none`
  FOLD_IN_RATING — minimum holistic rating to qualify: `mixed` (default) or `net_positive`
  GH_TOKEN       — must be set for `gh pr create`

Idempotent: failures (e.g., PR already exists) are logged but don't fail the run.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys


RATING_RANK = {"net_negative": 0, "mixed": 1, "net_positive": 2}


def fold_in_pr_body(goal: dict, verdict: dict, baseline: dict, best: dict) -> str:
    title = goal.get("title", goal.get("id", "?"))
    metric_baseline = baseline.get("value")
    metric_final = best.get("value")
    direction = goal.get("direction", "?")
    set_at_iter = best.get("set_at_iter")

    summary = verdict.get("summary", "")
    rating = verdict.get("rating", "?")
    confidence = verdict.get("confidence", "?")
    metric_validity = verdict.get("metric_validity", "?")
    iteration_pattern = verdict.get("iteration_pattern", "?")
    recommendation = verdict.get("recommendation", "?")
    wins = verdict.get("key_wins") or []
    concerns = verdict.get("key_concerns") or []

    wins_block = "\n".join(f"- {w}" for w in wins) or "_(none stated)_"
    concerns_block = "\n".join(f"- {c}" for c in concerns) or "_(none stated)_"

    return f"""## Autoresearch fold-in

This PR folds the **{title}** experiment branch into main.

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

- **Metric validity:** {metric_validity}
- **Iteration pattern:** {iteration_pattern}
- **Recommendation:** {recommendation}

---
*Folded in by [claude-autoresearch-action](https://github.com/dylan-murray/claude-autoresearch-action). Per-iteration review was performed by the same automated pipeline; review carefully before merging.*"""


def collect_verdicts(art_dir: str) -> list[tuple[str, dict, dict, dict, dict]]:
    """Return list of (goal_id, goal, verdict, baseline, best) tuples for all goals
    that produced both a holistic verdict and a loop artifact."""
    out = []
    for verdict_dir in sorted(glob.glob(os.path.join(art_dir, "verdict-*"))):
        goal_id = os.path.basename(verdict_dir).removeprefix("verdict-")
        verdict_path = os.path.join(verdict_dir, "holistic-verdict.json")
        loop_dir = os.path.join(art_dir, f"loop-{goal_id}")
        goal_path = os.path.join(loop_dir, "goal.json")
        baseline_path = os.path.join(loop_dir, "baseline.json")
        best_path = os.path.join(loop_dir, "best.json")

        for p in (verdict_path, goal_path, baseline_path, best_path):
            if not os.path.isfile(p):
                print(f"warning: missing {p}; skipping {goal_id}", file=sys.stderr)
                break
        else:
            with open(verdict_path) as f:
                verdict = json.load(f)
            with open(goal_path) as f:
                goal = json.load(f)
            with open(baseline_path) as f:
                baseline = json.load(f)
            with open(best_path) as f:
                best = json.load(f)
            out.append((goal_id, goal, verdict, baseline, best))
    return out


def qualifies(verdict: dict, min_rating: str) -> bool:
    rating = verdict.get("rating", "")
    return RATING_RANK.get(rating, -1) >= RATING_RANK.get(min_rating, 1)


def main() -> int:
    mode = os.environ.get("FOLD_IN_MODE", "all_above_threshold")
    min_rating = os.environ.get("FOLD_IN_RATING", "mixed")
    run_id = os.environ.get("RUN_ID", "unknown")
    art_dir = os.environ.get("ART_DIR", ".autoresearch/_artifacts")

    if mode == "none":
        print("FOLD_IN_MODE=none, no PRs opened")
        return 0

    items = collect_verdicts(art_dir)
    if not items:
        print(f"No verdict artifacts found in {art_dir}; no PRs opened")
        return 0

    print(f"Found {len(items)} goal verdict(s) for run {run_id}")

    qualifying = [t for t in items if qualifies(t[2], min_rating)]

    if mode == "best":
        if not qualifying:
            print(f"No goals qualify (need rating ≥ {min_rating}); no PR opened")
            return 0
        # Highest holistic rating, tiebreak by confidence
        best_tuple = max(
            qualifying,
            key=lambda t: (
                RATING_RANK.get(t[2].get("rating", ""), -1),
                t[2].get("confidence") or 0,
            ),
        )
        targets = [best_tuple]
    elif mode == "all_above_threshold":
        targets = qualifying
    else:
        print(f"Unknown FOLD_IN_MODE: {mode}", file=sys.stderr)
        return 2

    if not targets:
        print(f"No goals meet rating ≥ {min_rating}; no PR opened")
        return 0

    for goal_id, goal, verdict, baseline, best in targets:
        branch = f"autoresearch/exp/{run_id}/{goal_id}"
        title = f"autoresearch[{verdict.get('rating', '?')}]: {goal.get('title', goal_id)}"
        body = fold_in_pr_body(goal, verdict, baseline, best)
        cmd = [
            "gh", "pr", "create",
            "--base", "main",
            "--head", branch,
            "--title", title,
            "--label", "autoresearch",
            "--label", f"autoresearch-{verdict.get('rating', 'unknown')}",
            "--body", body,
        ]
        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
            print(f"Opened fold-in PR for {goal_id}: {out.strip()}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to open fold-in PR for {goal_id}: {e.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
