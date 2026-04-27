# Autoresearch: Optimize digest_event throughput

## Objective
Optimize the `digest_event()` function in `scripts/pi_rpc_driver.py` for maximum event-processing throughput. This pure function is called on every JSONL event from Pi's RPC stream — thousands per session. Faster processing reduces CPU overhead and lets the driver handle higher event rates.

## Metrics
- **Primary**: `events_per_sec` (unitless, higher is better) — events processed per second
- **Secondary**: None currently tracked

## How to Run
`./autoresearch.sh` — generates representative events, runs `digest_event` on them in a tight loop, reports throughput as `METRIC events_per_sec=<number>`.

## Files in Scope
- `scripts/pi_rpc_driver.py` — contains `digest_event()` and `truncate()` helpers. The entire file may be optimized as long as behavior is preserved.
- `tests/test_pi_rpc_driver.py` — test suite that validates correctness of `digest_event`

## Off Limits
- `action.yml` — the GitHub Action definition
- `pyproject.toml` — project config
- `scripts/pi_rpc_driver.py:main()` — the driver loop itself (focus on the pure helpers)

## Constraints
- All existing pytest tests must pass (`autoresearch.checks.sh`)
- No new dependencies
- `digest_event` must produce identical output for identical input

## What's Been Tried
(Updated as experiments accumulate)
