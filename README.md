# pi-autoresearch-action 🔬

Run [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) — autonomous experiment loops via the [Pi coding agent](https://pi.dev) — as a GitHub Action. Bring any LLM (ollama, anthropic, openai); pi-autoresearch owns the loop, we just plumb it.

## ⚙️ What this is

A reusable GitHub workflow that:

1. Installs Pi (`@mariozechner/pi-coding-agent`) and the `pi-autoresearch` extension on the runner
2. Optionally installs ollama (when `pi-provider: ollama`)
3. Spawns `pi --mode rpc --provider X --model Y`
4. Sends a single kickoff message — `/skill:autoresearch-create` plus your goal
5. pi-autoresearch handles the entire loop: try → measure → keep or revert → repeat, capped by `maxIterations`
6. When the cap is hit (or the wall-clock backstop fires), pushes the experiment branch and opens a PR with the session log in the body

The whole loop lives inside Pi's runtime. This action is a thin, reusable wrapper.

## 🚀 Quickstart

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
jobs:
  autoresearch:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: dylan-murray/pi-autoresearch-action@main
        with:
          pi-provider: 'ollama'
          pi-model: 'kimi-k2.6:cloud'
          goal: ${{ inputs.goal }}
          max-iterations: '10'
        env:
          OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}
```

## 🔑 Provider keys

Provider keys flow via `env:` on the step — Pi reads its provider's standard env var directly. Set whichever matches your `pi-provider`:

| Provider | Env var |
|---|---|
| `ollama` | `OLLAMA_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `google` | `GEMINI_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `mistral` | `MISTRAL_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `xai` | `XAI_API_KEY` |
| `cerebras` | `CEREBRAS_API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY` |

Bedrock and Azure aren't wired here yet (they need OIDC / IAM setup).

## 🎯 Two modes

- **Auto-goal** (`goal: ''` or omitted): the agent scans the repo and picks a meaningful metric on its own. Optionally steer with `focus: 'tests,perf'` and `ignore: 'vendor/**,node_modules/**'`.
- **Explicit goal** (`goal: '...'`): you describe what to optimize, the metric command, and the backpressure check. More predictable; use when you know what you want.

## 📥 Inputs

| Input | Default | Notes |
|---|---|---|
| `pi-provider` | *(required)* | Anything Pi supports — `ollama`, `anthropic`, `openai`, `google`, `groq`, `mistral`, `openrouter`, `xai`, `cerebras`, `deepseek`, etc. |
| `pi-model` | *(required)* | Model id (e.g. `kimi-k2.6:cloud`, `anthropic/claude-sonnet-4-6`, `openrouter/google/gemini-2.0-flash`) |
| `goal` | `''` | Goal text. Empty → auto-goal mode. |
| `focus` | `''` | Auto-goal only: comma-sep focus areas (`tests,perf,docs`) |
| `ignore` | `''` | Auto-goal only: comma-sep glob patterns to avoid |
| `max-iterations` | `'10'` | Written to `autoresearch.config.json`. pi-autoresearch self-stops at this cap. |
| `driver-timeout-seconds` | `'3300'` | Wall-clock backstop for the RPC driver. Should be less than the job's `timeout-minutes` × 60 to leave room for harvest + PR. |
| `pi-autoresearch-ref` | `https://github.com/davebcn87/pi-autoresearch` | Pin to a commit for reproducibility |
| `base-branch` | `'main'` | Branch to base the experiment on, and to PR against |
| `open-pr` | `'true'` | Set `'false'` to push the branch but skip the PR |
| `git-user-name` | `autoresearch-bot` | |
| `git-user-email` | `autoresearch-bot@users.noreply.github.com` | |

## 📤 Outputs

| Output | Description |
|---|---|
| `run-id` | Generated run id |
| `branch` | Experiment branch name |
| `kept-commits` | Number of commits the loop kept |
| `pr-url` | PR URL if one was opened |

## 🔧 What the action does

```
install pi + pi-autoresearch extension
install ollama (if provider=ollama)
create experiment branch from base
write autoresearch.config.json (with maxIterations)
spawn `pi --mode rpc --provider X --model Y`
scripts/pi_rpc_driver.py:
  • send /skill:autoresearch-create with goal (or auto-goal kickoff)
  • stream JSONL events to pi-events.jsonl
  • poll get_state every 30s, exit when idle for 2 consecutive checks
  • abort + exit on wall-clock timeout
push experiment branch
open PR (if any commits kept and open-pr: true)
upload run artifacts
```

## 📦 What gets opened on your repo

Per run:
- A branch `autoresearch/exp/<run-id>` with whatever pi-autoresearch kept
- A PR against `main` with the goal, provider/model, and `autoresearch.md` session log in the body — only if at least one commit landed

## 💸 Cost and rate limits

pi-autoresearch loops are autonomous — they can burn tokens fast. Cap with `max-iterations` and your provider's per-key billing limits.

## 📄 License

MIT
