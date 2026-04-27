# pi-autoresearch-action 🔬

Run [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) — autonomous experiment loops via the [Pi coding agent](https://pi.dev) — as a GitHub Action. Bring any LLM Pi supports; pi-autoresearch owns the loop, we just plumb it.

## ⚙️ How it works

The action installs Pi (`@mariozechner/pi-coding-agent`) and the `pi-autoresearch` extension on the runner, spawns Pi in RPC mode, and sends a single kickoff that invokes `/skill:autoresearch-create` with your goal (or empty for auto-goal mode). pi-autoresearch then runs the loop — try → measure → keep or revert → repeat — capped by `maxIterations`. When the cap hits (or our wall-clock backstop fires), the action pushes pi's experiment branch and opens a PR with the session log in the body. The whole loop lives inside Pi's runtime; this action is a thin reusable wrapper.

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
| `pi-model` | *(required)* | Model id Pi accepts for the chosen provider (run `pi --list-models` locally to discover). |
| `goal` | `''` | Goal text. Empty → auto-goal mode. |
| `focus` | `''` | Auto-goal only: comma-sep focus areas (`tests,perf,docs`) |
| `ignore` | `''` | Auto-goal only: comma-sep glob patterns to avoid |
| `max-iterations` | `'10'` | Written to `autoresearch.config.json`. pi-autoresearch self-stops at this cap. |
| `driver-timeout-seconds` | `'3300'` | Wall-clock backstop for the RPC driver. Should be less than the job's `timeout-minutes` × 60 to leave room for harvest + PR. |
| `pi-autoresearch-ref` | `https://github.com/davebcn87/pi-autoresearch` | Pin to a commit for reproducibility |
| `base-branch` | `'main'` | Branch to base the experiment on, and to PR against |
| `open-pr` | `'true'` | Set `'false'` to push the branch but skip the PR |
| `stream-events` | `'false'` | Print a live transcript of pi's activity to the action log. ⚠️ Event content can include file bodies / tool args / env values — on public repos these logs are world-readable. |
| `git-user-name` | `autoresearch-bot` | |
| `git-user-email` | `autoresearch-bot@users.noreply.github.com` | |

## 📤 Outputs

| Output | Description |
|---|---|
| `run-id` | Generated run id |
| `branch` | Experiment branch name |
| `kept-commits` | Number of commits the loop kept |
| `pr-url` | PR URL if one was opened |

## 📦 What gets opened on your repo

Per run:
- A branch `autoresearch/<goal-slug>-<date>` (created by pi-autoresearch) with whatever the loop kept
- The session files (`autoresearch.md`, `.sh`, `.checks.sh`, `.jsonl`, `.config.json`) live in `.autoresearch/exp/<run-id>/` — `.gitignore .autoresearch/` to keep them out of merges
- A PR against `main` with the goal, provider/model, and `autoresearch.md` session log in the body — only if at least one commit landed

## 💸 Cost and rate limits

pi-autoresearch loops are autonomous — they can burn tokens fast. Cap with `max-iterations` and your provider's per-key billing limits.

## 📄 License

MIT
