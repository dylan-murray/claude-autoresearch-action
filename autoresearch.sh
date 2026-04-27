#!/bin/bash
set -euo pipefail

# Benchmark digest_event throughput
# Runs benchmark_digest.py which outputs METRIC events_per_sec=...
python3 benchmark_digest.py
