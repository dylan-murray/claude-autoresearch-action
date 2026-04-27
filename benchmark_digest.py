#!/usr/bin/env python3
"""Benchmark digest_event throughput from scripts/pi_rpc_driver.py.

Generates a representative batch of pi RPC events, then repeatedly processes
them through digest_event. Reports events per second (higher is better).
"""

import sys
import time
from pathlib import Path

# Ensure the scripts dir is on sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from pi_rpc_driver import digest_event

# ------- representative events covering all digest_event branches -------
EVENTS: list[dict] = [
    # get_state response — should be skipped (None)
    {"type": "response", "command": "get_state", "success": True},
    # prompt accepted
    {"type": "response", "command": "prompt", "success": True, "id": "kickoff"},
    # prompt rejected
    {"type": "response", "command": "prompt", "success": False, "id": "kickoff"},
    # thinking_end — should be skipped (None)
    {"type": "message_update", "assistantMessageEvent": {"type": "thinking_end", "content": "long internal trace"}},
    # text_end with content
    {"type": "message_update", "assistantMessageEvent": {"type": "text_end", "content": "I'll list the repo first."}},
    # text_end with partial (older shape)
    {"type": "message_update", "assistantMessageEvent": {"type": "text_end", "partial": {"content": [{"type": "text", "text": "from partial"}]}}},
    # text_end empty — should be skipped (None)
    {"type": "message_update", "assistantMessageEvent": {"type": "text_end", "content": ""}},
    # toolcall_end with string arg
    {"type": "message_update", "assistantMessageEvent": {"type": "toolcall_end", "toolCall": {"name": "bash", "arguments": {"command": "ls -la"}}}},
    # toolcall_end with numeric arg
    {"type": "message_update", "assistantMessageEvent": {"type": "toolcall_end", "toolCall": {"name": "log_experiment", "arguments": {"metric": 13}}}},
    # toolcall_end no args
    {"type": "message_update", "assistantMessageEvent": {"type": "toolcall_end", "toolCall": {"name": "abort", "arguments": {}}}},
    # toolresult
    {"type": "message_update", "assistantMessageEvent": {"type": "toolresult", "result": "METRIC todo_count=7"}},
    # unknown event type — should skip (None)
    {"type": "ping"},
    # long text (tests truncation path)
    {"type": "message_update", "assistantMessageEvent": {"type": "text_end", "content": "x" * 1000}},
    # toolcall with many args (realistic: run_experiment)
    {"type": "message_update", "assistantMessageEvent": {"type": "toolcall_end", "toolCall": {"name": "run_experiment", "arguments": {"command": "python3 benchmark.py", "timeout_seconds": 600}}}},
    # a non-assistant event type that should be ignored
    {"type": "message_update", "assistantMessageEvent": {"type": "some_unknown", "content": "blah"}},
]

EVENTS_PER_BATCH = len(EVENTS)

# ------- warmup then benchmark -------

def run_benchmark(n_batches: int) -> float:
    """Process the event list n_batches times, return events/sec."""
    t0 = time.perf_counter()
    for _ in range(n_batches):
        for ev in EVENTS:
            digest_event(ev)
    elapsed = time.perf_counter() - t0
    total_events = n_batches * EVENTS_PER_BATCH
    return total_events / elapsed


def main() -> int:
    # Warm up (don't measure)
    run_benchmark(1000)
    # Take several measurements and use the best (peak throughput)
    results: list[float] = []
    for _ in range(5):
        eps = run_benchmark(5000)
        results.append(eps)
    # Report median for noise resistance
    results.sort()
    median_eps = results[len(results) // 2]
    # Round to reasonable precision
    print(f"METRIC events_per_sec={median_eps:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
