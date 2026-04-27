# pi-autoresearch-action

> Run [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) — autonomous experiment loops via the [Pi coding agent](https://pi.dev) — as a GitHub Action. Bring any LLM (ollama, anthropic, openai); pi-autoresearch owns the loop, we just plumb it.

## What this is

A reusable GitHub workflow that:

1. Installs Pi (`@mariozechner/pi-coding-agent`) and the `pi-autoresearch` extension on the runner
2. Optionally installs ollama (when `pi-provider: ollama`)
3. Spawns `pi --mode rpc --provider X --model Y`
4. Sends a single kickoff message — `/skill:autoresearch-create` plus your goal
5. pi-autoresearch handles the entire loop: try → measure → keep or revert → repeat, capped by `maxIterations`
6. When the cap is hit (or the wall-clock backstop fires), pushes the experiment branch and opens a PR with the session log in the body

The whole loop lives inside Pi's runtime. This action is a thin, reusable wrapper.

## Why use this vs. a Claude-only autoresearch action

- **Bring your own model.** Pi has first-class support for 15+ providers (ollama, anthropic, openai, google, azure, bedrock, mistral, groq, …). Pick a cheap ollama-cloud model for iteration, a stronger model for judgment, swap mid-experiment.
- **No permission gates.** Pi runs with the user's full host permissions out of the box — no `--dangerously-skip-permissions` flags, no permission prompts to script around in CI.
- **The loop is someone else's problem.** pi-autoresearch is a polished extension with a dashboard, hooks, finalize skill, etc. We don't reimplement any of that.

## Quickstart

In your repo, copy this workflow to `.github/workflows/autoresearch.yml`:

```yaml
name: Autoresearch
on:
  workflow_dispatch:
    inputs:
      goal:
        description: 'What to optimize. Leave blank for auto-goal mode.'
        required: false
        default: ''
permissions:
  contents: write
  pull-requests: write
  issues: write
jobs:
  autoresearch:
    uses: dylan-murray/pi-autoresearch-action/.github/workflows/pi-autoresearch.yml@main
    secrets: inherit
    with:
      pi-provider: 'ollama'
      pi-model: 'gpt-oss:120b-cloud'
      goal: ${{ inputs.goal }}
      max-iterations: '10'
```

Set whichever secret matches your `pi-provider`. The action wires every simple-API-key provider Pi supports:

| Provider | Secret name |
|---|---|
| `ollama` | `OLLAMA_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `google` | `GOOGLE_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `mistral` | `MISTRAL_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `xai` | `XAI_API_KEY` |
| `cerebras` | `CEREBRAS_API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY` |

Bedrock and Azure aren't wired here yet (they need OIDC / IAM setup).

### Two modes

- **Auto-goal** (`goal: ''` or omitted): the agent scans the repo and picks a meaningful metric on its own — TODO count, lint warnings, type errors, test runtime, etc. Optionally steer with `focus: 'tests,perf'` and `ignore: 'vendor/**,node_modules/**'`.
- **Explicit goal** (`goal: '...'`): you describe what to optimize, the metric command, and the backpressure check. More predictable; use when you know what you want.

## Reusable workflow inputs

| Input | Default | Notes |
|---|---|---|
| `pi-provider` | *(required)* | Anything Pi supports — `ollama`, `anthropic`, `openai`, `google`, `groq`, `mistral`, `openrouter`, `xai`, `cerebras`, `deepseek`, etc. |
| `pi-model` | *(required)* | Model id (e.g. `gpt-oss:120b-cloud`, `anthropic/claude-sonnet-4-6`, `openrouter/google/gemini-2.0-flash`) |
| `goal` | `''` | Goal text. Empty → auto-goal mode. |
| `focus` | `''` | Auto-goal only: comma-sep focus areas (`tests,perf,docs`) |
| `ignore` | `''` | Auto-goal only: comma-sep glob patterns to avoid |
| `max-iterations` | `'10'` | Written to `autoresearch.config.json`. pi-autoresearch self-stops at this cap. |
| `timeout-minutes` | `'60'` | Wall-clock backstop. RPC driver fires `abort` ~5 min before this if pi hasn't stopped. |
| `pi-autoresearch-ref` | `https://github.com/davebcn87/pi-autoresearch` | Pin to a commit for reproducibility |
| `git-user-name` | `autoresearch-bot` | |
| `git-user-email` | `autoresearch-bot@users.noreply.github.com` | |

## Architecture

```
setup
  └─ generate run-id + branch name
       ↓
run-loop
  ├─ install pi + pi-autoresearch extension
  ├─ install ollama (if provider=ollama)
  ├─ create experiment branch from main
  ├─ write autoresearch.config.json
  ├─ spawn `pi --mode rpc --provider X --model Y`
  ├─ scripts/pi_rpc_driver.py:
  │     • send /skill:autoresearch-create with goal
  │     • stream JSONL events to pi-events.jsonl
  │     • poll get_state every 30s, exit when idle for 2 consecutive checks
  │     • abort + exit on wall-clock timeout
  └─ push experiment branch
       ↓
open-pr (only if branch has commits)
  └─ open PR with autoresearch.md session in the body
       ↓
finish (step summary)
```

## What gets opened on your repo

Per run:
- A branch `autoresearch/exp/<run-id>` with whatever pi-autoresearch kept
- A PR against `main` with the goal, provider/model, and `autoresearch.md` session log in the body — only if at least one commit landed

## Cost and rate limits

- pi-autoresearch loops are autonomous — they can burn tokens fast. Cap with `max-iterations` and your provider's per-key billing limits.
- For cheap iteration, use ollama-cloud models (`gpt-oss:120b-cloud`, `qwen3-coder:480b-cloud`, etc.) — typically much cheaper than frontier APIs.

## Smoke test

`.github/workflows/self-test.yml` dispatches the pipeline against `fixtures/todo-corpus/` with a tiny goal: reduce TODO count, guarded by `python3 -m py_compile`. 3 iterations, ~5 minutes, validates the install + RPC plumbing without burning real budget.

## License

MIT
