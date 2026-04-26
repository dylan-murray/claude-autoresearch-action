# claude-autoresearch-action

> Run an autoresearch optimization loop on your repo as a GitHub Action. Goal-driven, metric-validated, holistic-judged. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## What this is

A reusable GitHub Action that runs **autoresearch-style optimization loops** against your repo. The loop:

1. Picks ONE focused change to try (Claude agent: `iteration-runner`)
2. Commits it on an experiment branch
3. Runs your benchmark command, parses `METRIC name=value`
4. Runs your guard command (must exit 0)
5. **Keeps** the commit if the metric moved in the right direction; **`git revert`s** otherwise
6. Repeats until iteration cap or plateau

After the loop, an opus-class agent (`experiment-judge`) reads the full diff and gives a **holistic verdict** — "is this branch worth merging?" — alongside the mechanical metric.

For every goal that produced at least one kept commit, a PR is opened against `main` with the verdict + metric trajectory in the body. The human decides what to merge.

## What's different from karpathy/autoresearch

| | karpathy/autoresearch | claude-autoresearch-action |
|---|---|---|
| Input model | One goal + benchmark | One or N goals + benchmarks (auto-designed or explicit) |
| Execution | Single CLI loop | Parallel matrix (one optimization per goal) |
| Halt conditions | User interrupt | Iteration cap + plateau detection |
| End-of-run review | Metric only | Mechanical metric **+** opus holistic verdict |
| Guard mechanism | None | Optional command that must pass per iteration |
| Cross-run memory | None | State branch persists narrative + attempts log |
| Distribution | Local CLI | GitHub Action |

## Quickstart

In your repo, copy this workflow to `.github/workflows/autoresearch.yml`:

```yaml
name: Autoresearch
on:
  workflow_dispatch:
    inputs:
      goals:
        description: 'Optional JSON array of explicit goals — leave blank to let the goal-designer pick.'
        required: false
        default: ''
  schedule: [{ cron: '0 9 * * 1' }]   # Mondays 09:00 UTC
permissions:
  contents: write
  pull-requests: write
  issues: write
jobs:
  autoresearch:
    uses: dylan-murray/claude-autoresearch-action/.github/workflows/claude-autoresearch.yml@main
    secrets: inherit
    with:
      max-iterations-per-goal: '10'
      goals-per-run: '2'
      goals: ${{ inputs.goals || '' }}
```

Pass an explicit goal at dispatch time when you know exactly what you want optimized; leave it blank to let the `goal-designer` agent propose one against the repo. Goal JSON schema lives in `agents/goal-designer.md`.

Add a repo secret named `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) **or** `ANTHROPIC_API_KEY`. `secrets: inherit` passes whichever you have.

## Reusable workflow inputs

| Input | Default | Notes |
|---|---|---|
| `goals-per-run` | `'1'` | How many distinct goals the goal-designer should propose. Each becomes a parallel matrix cell. |
| `max-iterations-per-goal` | `'10'` | Iteration cap per goal. Each iteration is one propose/measure/keep-or-revert step. |
| `plateau-k` | `'3'` | Halt the loop after K consecutive iterations with no `kept`. |
| `max-parallel-goals` | `'2'` | Matrix max-parallel for goal cells. |
| `goals` | `''` | Optional JSON array of explicit goals (skips goal-designer ideation). See `agents/goal-designer.md` for the schema. |
| `focus` | `''` | Comma-separated focus areas (e.g. `tests,security,docs`) |
| `ignore` | `''` | Comma-separated glob patterns to ignore |
| `git-user-name` | `'autoresearch-bot'` | Git author for commits |
| `git-user-email` | `'autoresearch-bot@users.noreply.github.com'` | |
| `loop-timeout-minutes` | `'240'` | Per-goal timeout for the autoresearch-loop job. Bump if iterations are slow or `max-iterations-per-goal` is high. |

## Architecture

```
setup
  └─ goal-design (agent: goal-designer, sonnet 4.6)
       │  Reads repo, memory, attempts log. Proposes N {goal, benchmark, guard, direction, scope}.
       │  Or passes through user-supplied `goals` input.
       ↓
  ┌────────── matrix per goal ──────────┐
  │  autoresearch-loop                  │
  │    Per iteration:                   │
  │    1. iteration-runner agent picks  │
  │       ONE focused change, commits   │
  │    2. workflow runs benchmark_cmd   │
  │    3. workflow runs guard_cmd       │
  │    4. keep | revert | no_op         │
  │    Halts on cap or plateau-K        │
  │           ↓                          │
  │  experiment-judge (opus 4.7)        │
  │    Reads git diff main..HEAD        │
  │    Returns holistic verdict          │
  └─────────────────────────────────────┘
       ↓
  open-prs (one PR per goal with kept commits)
       ↓
  finish (publish report to step summary, persist state)
```

## Three agents, that's it

- **`goal-designer.md`** (sonnet 4.6) — picks what to optimize and how to measure it
- **`iteration-runner.md`** (sonnet 4.6) — proposes one focused change per iteration
- **`experiment-judge.md`** (opus 4.7) — reads the full branch and gives a holistic merge verdict

The mechanical loop (in `scripts/autoresearch_loop.py`) is the core; everything else is wrapping.

## What gets opened on your repo

Per goal, the action creates:

- A branch `autoresearch/exp/<run-id>/<goal-id>` with the kept commits from the loop
- A PR against `main` with the holistic verdict + metric trajectory + iteration log in the body (skipped if the loop produced zero kept commits)

It also persists narrative state to a `autoresearch-state` branch so future runs accumulate context.

## Cost

Roughly per goal:
- 1 goal-design call (sonnet)
- N iteration-runner calls (sonnet) — N up to `max-iterations-per-goal`
- 1 experiment-judge call (opus)

For a 2-goal × 10-iteration run: ~$5–15 depending on repo size and how chunky the diffs get.

## Smoke test

`.github/workflows/self-test.yml` dispatches the pipeline against a fixture (`fixtures/todo-corpus/`) with a deliberately simple goal: reduce TODO count, guarded by Python parse validity. Runs in ~5 minutes. Validates the loop end-to-end without burning real budget.

## License

MIT
