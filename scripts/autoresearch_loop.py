#!/usr/bin/env python3
"""Vendored autoresearch loop — one goal, N iterations, mechanical keep/revert.

Inspired by github.com/karpathy/autoresearch's pattern. Each iteration:
  1. Stage inputs for the iteration-runner agent
  2. Invoke the iteration-runner (one focused change, one commit)
  3. Run the goal's benchmark command, parse `METRIC name=value`
  4. Run the optional guard command — must exit 0
  5. If metric moved in `direction` AND guard passed: keep, push branch
  6. Else: `git revert HEAD --no-edit`, push
  7. Append iteration entry to log + update human-readable session.md
  8. Halt on iteration cap or plateau (K consecutive non-kept)

Inputs (env vars):
  RUN_ID                   — pipeline run id
  GOAL_ID                  — goal id (matches the experiment branch slug)
  BRANCH                   — autoresearch/exp/<run-id>/<goal-id>
  GOAL_FILE                — path to the goal JSON for this cell
  MAX_ITERATIONS           — iteration cap (default 10)
  PLATEAU_K                — stop after K consecutive non-kept (default 3)
  CLAUDE_CMD               — path to the claude CLI (default `claude`)
  CLAUDE_CODE_OAUTH_TOKEN  — auth (or ANTHROPIC_API_KEY)
  GH_TOKEN                 — for git push via the gh credential helper
  STATE_DIR                — base dir for per-goal state (default
                             .autoresearch/runs/<run-id>/<goal-id>/)

Outputs (incrementally written, partial runs leave usable state):
  <state_dir>/iteration-log.jsonl  — one line per iteration
  <state_dir>/best.json            — current best metric
  <state_dir>/session.md           — human-readable narrative

Exit codes:
  0 — loop completed (cap hit, plateau, or no-op exhaustion)
  2 — fatal config error (missing goal, malformed JSON, etc.)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
def shell(cmd: str, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def append_session_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(line + "\n")


# -----------------------------------------------------------------------------
# Metric parsing — `METRIC name=value` (one or more on stdout)
# -----------------------------------------------------------------------------
METRIC_RE = re.compile(r"METRIC\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?)")


def parse_metric_value(stdout: str, metric_name: str | None = None) -> float | None:
    """Find a METRIC line in stdout, return its numeric value.

    If metric_name is given, only return values matching that name. If None,
    return the first METRIC value found. Multiple METRIC lines on one stdout
    are allowed; this just picks one deterministically.
    """
    matches = METRIC_RE.findall(stdout)
    if not matches:
        return None
    if metric_name:
        for name, val in matches:
            if name == metric_name:
                try:
                    return float(val)
                except ValueError:
                    return None
        return None
    try:
        return float(matches[0][1])
    except ValueError:
        return None


def run_benchmark(cmd: str, cwd: Path) -> tuple[float | None, str]:
    """Run the goal's benchmark command, parse METRIC line. Return (value, raw_stdout)."""
    try:
        result = shell(cmd, cwd=cwd, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "(benchmark timed out after 60s)"
    return parse_metric_value(result.stdout), result.stdout


def run_guard(cmd: str | None, cwd: Path) -> tuple[bool, str]:
    """Run the optional guard command. Return (passed, stderr-or-stdout-snippet)."""
    if not cmd:
        return True, ""  # No guard => always passes
    try:
        result = shell(cmd, cwd=cwd, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "(guard timed out after 120s)"
    if result.returncode == 0:
        return True, ""
    snippet = (result.stderr or result.stdout or "")[:300]
    return False, snippet


def is_better(new_value: float, current_best: float, direction: str) -> bool:
    if direction == "higher_is_better":
        return new_value > current_best
    return new_value < current_best


# -----------------------------------------------------------------------------
# Iteration-runner invocation
# -----------------------------------------------------------------------------
def run_iteration_runner(
    *, claude_cmd: str, run_id: str, goal_id: str, branch: str, iteration: int
) -> tuple[bool, str]:
    prompt = (
        f"Run iteration {iteration} of the autoresearch loop. "
        f"Goal id: {goal_id}. Run id: {run_id}. Branch: {branch}.\n\n"
        f"Inputs are staged at .autoresearch/iteration/. Read them all (goal.json, "
        f"iteration-log.jsonl, best.json, session.md) before deciding what to try.\n\n"
        f"Make ONE focused change. Commit on the experiment branch with prefix "
        f"`iter <N>:`. Print `ITERATION_DESCRIPTION=\"...\"` to stdout. The "
        f"workflow handles measure + keep/revert."
    )
    cmd = [
        claude_cmd, "-p", prompt,
        "--agent", "iteration-runner",
        "--dangerously-skip-permissions",
    ]
    print(f"[iter {iteration}] invoking iteration-runner...", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print(f"[iter {iteration}] iteration-runner timed out (10 min)", flush=True)
        return False, ""
    if result.returncode != 0:
        print(
            f"[iter {iteration}] iteration-runner exited {result.returncode}: "
            f"{result.stderr[:300]}",
            flush=True,
        )
        return False, result.stdout
    return True, result.stdout


def parse_iteration_description(stdout: str) -> str:
    m = re.search(r'ITERATION_DESCRIPTION="([^"]*)"', stdout)
    return m.group(1) if m else "(no description provided)"


# -----------------------------------------------------------------------------
# Input staging
# -----------------------------------------------------------------------------
def stage_iteration_inputs(*, state_dir: Path, repo_root: Path) -> None:
    """Copy the canonical input files into .autoresearch/iteration/ where the
    iteration-runner agent reads from."""
    iter_dir = repo_root / ".autoresearch" / "iteration"
    iter_dir.mkdir(parents=True, exist_ok=True)

    for name in ["goal.json", "iteration-log.jsonl", "best.json", "session.md"]:
        src = state_dir / name
        dst = iter_dir / name
        if src.exists():
            dst.write_bytes(src.read_bytes())
        else:
            # Sensible empty placeholders so the agent doesn't crash on missing files
            if name.endswith(".jsonl"):
                dst.write_text("")
            elif name.endswith(".md"):
                dst.write_text("# Session\n\n_(empty — first iteration)_\n")
            else:
                dst.write_text("{}")


# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
def main() -> int:
    repo_root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    run_id = os.environ.get("RUN_ID")
    goal_id = os.environ.get("GOAL_ID")
    branch = os.environ.get("BRANCH")
    goal_file = os.environ.get("GOAL_FILE")
    max_iterations = int(os.environ.get("MAX_ITERATIONS", "10"))
    plateau_k = int(os.environ.get("PLATEAU_K", "3"))
    claude_cmd = os.environ.get("CLAUDE_CMD", "claude")
    state_dir_env = os.environ.get("STATE_DIR")

    if not all([run_id, goal_id, branch, goal_file]):
        print(
            "error: RUN_ID, GOAL_ID, BRANCH, GOAL_FILE all required",
            file=sys.stderr,
        )
        return 2

    state_dir = (
        Path(state_dir_env)
        if state_dir_env
        else repo_root / ".autoresearch" / "runs" / run_id / goal_id
    )
    state_dir.mkdir(parents=True, exist_ok=True)

    # Load goal definition
    goal = read_json(Path(goal_file))
    if not goal:
        print(f"error: failed to load goal from {goal_file}", file=sys.stderr)
        return 2

    benchmark_cmd = goal.get("benchmark_cmd")
    guard_cmd = goal.get("guard_cmd")
    direction = goal.get("direction", "higher_is_better")
    metric_name = goal.get("metric_name")  # optional — picks first METRIC line if absent

    if not benchmark_cmd:
        print(f"error: goal {goal_id} has no benchmark_cmd", file=sys.stderr)
        return 2

    # Place a copy of the goal in the state dir for downstream stages to reference
    write_json(state_dir / "goal.json", goal)

    # Capture baseline by running the benchmark on current HEAD
    baseline_value, baseline_stdout = run_benchmark(benchmark_cmd, cwd=repo_root)
    if baseline_value is None:
        print(
            "error: baseline benchmark produced no parseable METRIC line. stdout:\n"
            + baseline_stdout[:500],
            file=sys.stderr,
        )
        return 2

    write_json(state_dir / "baseline.json", {"value": baseline_value})
    write_json(
        state_dir / "best.json",
        {"value": baseline_value, "set_at_iter": 0, "commit": None},
    )

    log_path = state_dir / "iteration-log.jsonl"
    session_path = state_dir / "session.md"

    # Initialize session.md
    session_path.write_text(
        f"# Autoresearch session — `{goal_id}`\n\n"
        f"**Goal:** {goal.get('title', goal_id)}\n\n"
        f"**Direction:** {direction}\n\n"
        f"**Baseline:** {baseline_value}\n\n"
        f"## Iterations\n\n"
    )

    print(
        f"[loop] starting; goal={goal_id} direction={direction} "
        f"baseline={baseline_value} max_iter={max_iterations} plateau_k={plateau_k}",
        flush=True,
    )

    consecutive_no_keep = 0
    for iteration in range(1, max_iterations + 1):
        stage_iteration_inputs(state_dir=state_dir, repo_root=repo_root)

        pre_head = shell("git rev-parse HEAD", cwd=repo_root).stdout.strip()

        ok, stdout = run_iteration_runner(
            claude_cmd=claude_cmd,
            run_id=run_id,
            goal_id=goal_id,
            branch=branch,
            iteration=iteration,
        )
        if not ok:
            entry = {
                "iter": iteration, "commit": None, "metric": None, "delta": None,
                "status": "error", "what": "iteration-runner failed", "ts": time.time(),
            }
            append_jsonl(log_path, entry)
            append_session_line(
                session_path,
                f"- **iter {iteration}** — `error` — iteration-runner failed",
            )
            consecutive_no_keep += 1
            if consecutive_no_keep >= plateau_k:
                print(f"[loop] {plateau_k} consecutive non-kept; halting", flush=True)
                break
            continue

        post_head = shell("git rev-parse HEAD", cwd=repo_root).stdout.strip()
        description = parse_iteration_description(stdout)

        if pre_head == post_head:
            entry = {
                "iter": iteration, "commit": None, "metric": None, "delta": None,
                "status": "no_op", "what": description, "ts": time.time(),
            }
            append_jsonl(log_path, entry)
            append_session_line(
                session_path, f"- **iter {iteration}** — `no_op` — {description}"
            )
            consecutive_no_keep += 1
            if consecutive_no_keep >= plateau_k:
                print(f"[loop] {plateau_k} consecutive no_op; halting", flush=True)
                break
            continue

        # Run benchmark
        new_value, _bench_stdout = run_benchmark(benchmark_cmd, cwd=repo_root)
        if new_value is None:
            print(f"[iter {iteration}] benchmark failed; reverting", flush=True)
            shell(f"git revert --no-edit {post_head}", cwd=repo_root)
            shell(f"git push origin {branch}", cwd=repo_root)
            entry = {
                "iter": iteration, "commit": post_head, "metric": None, "delta": None,
                "status": "metric_error", "what": description, "ts": time.time(),
            }
            append_jsonl(log_path, entry)
            append_session_line(
                session_path,
                f"- **iter {iteration}** — `metric_error` — benchmark failed; reverted",
            )
            consecutive_no_keep += 1
        else:
            best_value = read_json(state_dir / "best.json", {}).get("value", baseline_value)
            metric_better = is_better(new_value, best_value, direction)

            # Run guard — must pass for the iteration to be kept
            guard_passed, guard_msg = run_guard(guard_cmd, cwd=repo_root)

            if metric_better and guard_passed:
                shell(f"git push origin {branch}", cwd=repo_root)
                write_json(
                    state_dir / "best.json",
                    {"value": new_value, "set_at_iter": iteration, "commit": post_head},
                )
                entry = {
                    "iter": iteration, "commit": post_head, "metric": new_value,
                    "delta": new_value - best_value, "status": "kept",
                    "what": description, "ts": time.time(),
                }
                append_jsonl(log_path, entry)
                append_session_line(
                    session_path,
                    f"- **iter {iteration}** — ✓ `kept` — `{best_value} → {new_value}` — {description}",
                )
                print(
                    f"[iter {iteration}] kept: {best_value} → {new_value} ({description})",
                    flush=True,
                )
                consecutive_no_keep = 0
            else:
                # Revert
                shell(f"git revert --no-edit {post_head}", cwd=repo_root)
                shell(f"git push origin {branch}", cwd=repo_root)
                if not guard_passed:
                    status = "guard_failed"
                    reason = f"guard failed: {guard_msg}"
                else:
                    status = "reverted"
                    reason = f"metric not better ({best_value} → {new_value}, direction={direction})"
                entry = {
                    "iter": iteration, "commit": post_head, "metric": new_value,
                    "delta": new_value - best_value, "status": status,
                    "what": description, "ts": time.time(),
                    "reason": reason,
                }
                append_jsonl(log_path, entry)
                append_session_line(
                    session_path,
                    f"- **iter {iteration}** — ✗ `{status}` — {reason} — {description}",
                )
                print(f"[iter {iteration}] {status}: {reason}", flush=True)
                consecutive_no_keep += 1

        if consecutive_no_keep >= plateau_k:
            print(f"[loop] plateau detected ({plateau_k} consecutive non-kept); halting", flush=True)
            break

    final_best = read_json(state_dir / "best.json", {})
    print(
        f"[loop] done; final best={final_best.get('value')} "
        f"set at iter {final_best.get('set_at_iter')}",
        flush=True,
    )
    append_session_line(
        session_path,
        f"\n## Final\n\n**Best metric:** {final_best.get('value')} "
        f"(set at iter {final_best.get('set_at_iter')})",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
