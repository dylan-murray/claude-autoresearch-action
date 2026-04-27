#!/usr/bin/env python3
"""Drive `pi --mode rpc` to run the pi-autoresearch loop until it self-stops.

pi-autoresearch (an extension for Mario Zechner's Pi coding agent) owns the
inner loop: it picks a change, commits it, runs the benchmark via its
`run_experiment` tool, decides keep/revert, and repeats until `maxIterations`
is hit. Our job is to:

  1. Spawn `pi --mode rpc --provider X --model Y`
  2. Send the kickoff as a single user message (a slash command that invokes
     the autoresearch-create skill with our goal stuffed in)
  3. Tail JSONL events from stdout, mirror them to a log
  4. Poll `get_state` periodically — when the agent has been idle
     (`isStreaming: false`, `pendingMessageCount: 0`) for two consecutive
     checks, we declare the loop done and exit
  5. Wall-clock backstop: if `TIMEOUT_SECONDS` elapses first, send `abort`
     and exit anyway so the runner always cleans up

We deliberately do NOT try to micromanage the loop — pi-autoresearch already
handles iteration accounting via its `autoresearch.config.json` (which the
workflow writes before invoking us).

Inputs (env vars):
  PI_PROVIDER       provider id passed to `pi --provider` (e.g. "ollama")
  PI_MODEL          model id passed to `pi --model` (e.g. "gpt-oss:120b-cloud")
  GOAL_TEXT         the goal description. Empty string → auto-goal mode:
                    pi-autoresearch picks its own metric based on the repo.
  AUTO_GOAL_FOCUS   auto-mode only — comma-sep focus areas (tests, perf, ...)
  AUTO_GOAL_IGNORE  auto-mode only — comma-sep glob patterns to avoid
  TIMEOUT_SECONDS   wall-clock backstop (default 3600)
  PI_BIN            path to pi binary (default "pi")
  EVENT_LOG         path to write JSONL event log (default ./pi-events.jsonl)

Exit codes:
  0   loop completed (cap hit OR timeout backstop fired)
  2   spawn failed / protocol error (pi exited unexpectedly)
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def stderr(msg: str) -> None:
    print(f"[pi-driver] {msg}", file=sys.stderr, flush=True)


def reader_thread(stream, q: queue.Queue) -> None:
    """Forward each stdout line into the event queue. EOF → sentinel None."""
    for line in iter(stream.readline, ""):
        q.put(line.rstrip("\n").rstrip("\r"))
    q.put(None)


def send(proc: subprocess.Popen, msg: dict) -> None:
    """Write a single JSONL command to pi's stdin."""
    line = json.dumps(msg)
    assert proc.stdin is not None
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def main() -> int:
    provider = os.environ.get("PI_PROVIDER", "")
    model = os.environ.get("PI_MODEL", "")
    goal_text = os.environ.get("GOAL_TEXT", "").strip()
    auto_focus = os.environ.get("AUTO_GOAL_FOCUS", "").strip()
    auto_ignore = os.environ.get("AUTO_GOAL_IGNORE", "").strip()
    timeout = int(os.environ.get("TIMEOUT_SECONDS", "3600"))
    pi_bin = os.environ.get("PI_BIN", "pi")
    event_log = Path(os.environ.get("EVENT_LOG", "pi-events.jsonl"))

    if not provider or not model:
        stderr("PI_PROVIDER and PI_MODEL are required")
        return 2

    cmd = [pi_bin, "--mode", "rpc", "--provider", provider, "--model", model]
    stderr(f"spawning: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        stderr(f"pi binary not found at {pi_bin!r}")
        return 2

    q: queue.Queue = queue.Queue()
    t = threading.Thread(target=reader_thread, args=(proc.stdout, q), daemon=True)
    t.start()

    event_log.parent.mkdir(parents=True, exist_ok=True)
    log_fh = event_log.open("w", buffering=1)

    if goal_text:
        kickoff_message = (
            "/skill:autoresearch-create\n\n"
            f"{goal_text}\n\n"
            "Use the maxIterations from autoresearch.config.json (already written). "
            "Stop when that cap is reached. Auto-commit kept iterations. Do not "
            "ask follow-up questions — infer from this prompt and the repo."
        )
        stderr(f"kickoff (explicit goal): {goal_text[:80]}...")
    else:
        # Auto-goal mode: ask pi-autoresearch to scan the repo and pick a
        # meaningful metric to optimize on its own. Pass focus/ignore hints
        # so the user can steer without writing a full goal.
        steers: list[str] = []
        if auto_focus:
            steers.append(f"Focus areas: {auto_focus}.")
        if auto_ignore:
            steers.append(f"Avoid these globs: {auto_ignore}.")
        steer_block = ("\n\n" + "\n".join(steers)) if steers else ""
        kickoff_message = (
            "/skill:autoresearch-create\n\n"
            "Auto-goal mode. Scan the repository and pick ONE meaningful, "
            "mechanically-measurable metric to optimize. Examples of good "
            "targets: lint warnings, type errors, test count, test runtime, "
            "TODO count, coverage gap, dead-code lines. Avoid subjective "
            "metrics. The benchmark must run in under 60s and print a single "
            "`METRIC name=value` line. Define a backpressure check (build/"
            "tests pass) so regressions revert. Then start iterating."
            f"{steer_block}\n\n"
            "Use the maxIterations from autoresearch.config.json (already "
            "written). Stop when that cap is reached. Auto-commit kept "
            "iterations. Do not ask follow-up questions — infer from the repo."
        )
        stderr("kickoff (auto-goal mode)")
    kickoff = {"id": "kickoff", "type": "prompt", "message": kickoff_message}
    send(proc, kickoff)

    deadline = time.time() + timeout
    last_state_check = 0.0
    state_check_interval = 30.0
    consecutive_idle = 0
    state_req_id = 0

    def poll_state() -> None:
        nonlocal state_req_id
        state_req_id += 1
        send(proc, {"id": f"state-{state_req_id}", "type": "get_state"})

    while True:
        if proc.poll() is not None:
            stderr(f"pi exited with code {proc.returncode}")
            break

        now = time.time()
        if now > deadline:
            stderr("wall-clock timeout reached — sending abort")
            send(proc, {"id": "abort1", "type": "abort"})
            time.sleep(2)
            break

        if now - last_state_check >= state_check_interval:
            poll_state()
            last_state_check = now

        try:
            line = q.get(timeout=1.0)
        except queue.Empty:
            continue

        if line is None:
            stderr("pi stdout closed")
            break

        # Mirror raw lines to the event log; parse what we recognize
        log_fh.write(line + "\n")

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        # State response → idleness detection
        if (
            event.get("type") == "response"
            and event.get("command") == "get_state"
            and event.get("success")
        ):
            data = event.get("data") or {}
            is_streaming = bool(data.get("isStreaming"))
            pending = int(data.get("pendingMessageCount") or 0)
            if not is_streaming and pending == 0:
                consecutive_idle += 1
                stderr(
                    f"idle check {consecutive_idle}/2 "
                    f"(streaming={is_streaming}, pending={pending})"
                )
                if consecutive_idle >= 2:
                    stderr("agent idle for two consecutive checks — done")
                    break
            else:
                consecutive_idle = 0

    log_fh.close()

    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    stderr(f"event log: {event_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
