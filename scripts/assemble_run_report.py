#!/usr/bin/env python3
"""Assemble the final run report markdown from per-goal artifacts.

Called by the finish job in .github/workflows/claude-autoresearch.yml. Output
is piped to $GITHUB_STEP_SUMMARY so the report appears on the workflow run
page directly.

Inputs (read from --artifacts-dir):
  loop-<goal_id>/    — per-goal: goal.json, iteration-log.jsonl, best.json,
                       baseline.json, session.md
  verdict-<goal_id>/ — per-goal: holistic-verdict.json

Env vars:
  RUN_ID — pipeline run id
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys


RATING_BADGE = {
    "net_positive": "✅ net_positive",
    "mixed": "⚠️ mixed",
    "net_negative": "❌ net_negative",
}


def load_json(path: str, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def count_iter_statuses(log_path: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not os.path.isfile(log_path):
        return counts
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
                counts[status] = counts.get(status, 0) + 1
    except OSError:
        pass
    return counts


def render(art_dir: str, run_id: str) -> str:
    out: list[str] = []
    out.append(f"# Autoresearch run `{run_id}`")
    out.append("")

    goal_dirs = sorted(glob.glob(os.path.join(art_dir, "loop-*")))
    if not goal_dirs:
        out.append("_No goals produced loop artifacts. Check the per-goal job logs._")
        return "\n".join(out)

    out.append("## Per-goal results")
    out.append("")
    out.append("| Goal | Iterations (kept/total) | Baseline → Best | Holistic | Recommendation |")
    out.append("|---|---|---|---|---|")

    for d in goal_dirs:
        goal_id = os.path.basename(d).removeprefix("loop-")
        goal = load_json(os.path.join(d, "goal.json"), {}) or {}
        baseline = load_json(os.path.join(d, "baseline.json"), {}) or {}
        best = load_json(os.path.join(d, "best.json"), {}) or {}
        verdict = load_json(
            os.path.join(art_dir, f"verdict-{goal_id}", "holistic-verdict.json"), {}
        ) or {}
        statuses = count_iter_statuses(os.path.join(d, "iteration-log.jsonl"))

        title = goal.get("title", goal_id)
        kept = statuses.get("kept", 0)
        total = sum(statuses.values())
        iter_summary = f"{kept}/{total}" if total else "0/0"
        metric_baseline = baseline.get("value", "?")
        metric_final = best.get("value", "?")
        rating = verdict.get("rating", "—")
        rating_badge = RATING_BADGE.get(rating, rating)
        recommendation = verdict.get("recommendation", "—")

        out.append(
            f"| **{title}** (`{goal_id}`) | {iter_summary} | "
            f"`{metric_baseline}` → `{metric_final}` | {rating_badge} | {recommendation} |"
        )
    out.append("")

    # Per-goal detailed sections
    out.append("## Holistic verdicts")
    out.append("")
    for d in goal_dirs:
        goal_id = os.path.basename(d).removeprefix("loop-")
        verdict = load_json(
            os.path.join(art_dir, f"verdict-{goal_id}", "holistic-verdict.json"), {}
        )
        if not verdict:
            continue
        goal = load_json(os.path.join(d, "goal.json"), {}) or {}
        title = goal.get("title", goal_id)
        out.append(f"### `{goal_id}` — {title}")
        out.append("")
        rating = verdict.get("rating", "?")
        confidence = verdict.get("confidence", "?")
        out.append(f"**Rating:** {RATING_BADGE.get(rating, rating)} (confidence {confidence})")
        out.append("")
        summary = verdict.get("summary", "")
        if summary:
            out.append(f"> {summary}")
            out.append("")
        wins = verdict.get("key_wins") or []
        if wins:
            out.append("**Key wins:**")
            for w in wins:
                out.append(f"- {w}")
            out.append("")
        concerns = verdict.get("key_concerns") or []
        if concerns:
            out.append("**Key concerns:**")
            for c in concerns:
                out.append(f"- {c}")
            out.append("")

    # Iteration session docs as collapsible details
    out.append("## Iteration sessions")
    out.append("")
    for d in goal_dirs:
        goal_id = os.path.basename(d).removeprefix("loop-")
        session_path = os.path.join(d, "session.md")
        if not os.path.isfile(session_path):
            continue
        try:
            with open(session_path) as f:
                session_md = f.read()
        except OSError:
            continue
        out.append(f"<details><summary>Session log — <code>{goal_id}</code></summary>\n")
        out.append("")
        out.append(session_md)
        out.append("")
        out.append("</details>")
        out.append("")

    out.append("---")
    out.append("_Generated by `.github/workflows/claude-autoresearch.yml`._")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--artifacts-dir", default=".autoresearch/_artifacts")
    args = p.parse_args()

    run_id = os.environ.get("RUN_ID", "unknown")
    print(render(args.artifacts_dir, run_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
