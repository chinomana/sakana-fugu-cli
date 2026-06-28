# 🐡 Fugu Vibe CLI

A specialized CLI for **Sakana Fugu** vibe coding with async voice control, agent orchestration visualization, and unlimited prompt mode.

> **Fugu** is Sakana AI's learned multi-agent orchestration system that dynamically routes between 1-3 expert agents per request. This CLI is designed to fully leverage Fugu's unique architecture.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧭 **Orchestration Visualization** | Real-time dashboard showing Fugu's internal routing decisions, worker activation, and verification phases |
| 🎤 **Voice Control** | Push-to-talk voice input with VAD auto-segmentation and Faster-Whisper STT |
| ⚡ **Async Tasks** | Parallel task execution with git-worktree isolation and DAG dependency management |
| 🔓 **Unlimited Mode** | Override safety guardrails for unrestricted prompt control |
| 📡 **Full API Support** | Complete Responses API support with all Fugu-specific parameters |
| 🔄 **Stream Resilience** | 2-hour idle timeout, automatic reconnection, Sakana-recommended retry policies |

## 🚀 Quick Start

### Requirements

- Python 3.11+ (recommended: 3.12; 3.14 has known `pyexpat` issues on macOS)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip 24+

### Install from source

```bash
# Clone
git clone https://github.com/fugu-vibe/fugu-vibe-cli.git
cd fugu-vibe-cli

# Install with uv (recommended)
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .

# Or with pip
pip install -e ".[all]"
```

### Authentication

```bash
# Set API key (get from https://console.sakana.ai/api-keys or your proxy provider)
export SAKANA_API_KEY="your-key-here"

# Or use the auth command
fugu-vibe auth login
```

### Start Vibe Coding

```bash
# Interactive session with full dashboard
fugu-vibe vibe

# Use Fugu Ultra with max reasoning
fugu-vibe vibe --model fugu-ultra --effort xhigh

# With a custom / proxy base URL
fugu-vibe vibe --base-url https://your-proxy.com/v1

# With voice control
fugu-vibe vibe --voice

# Unlimited prompt mode (no guardrails)
fugu-vibe vibe --unlimited
```

## 📋 Commands

### `vibe` — Interactive Session

```bash
fugu-vibe vibe [OPTIONS]

Options:
  -m, --model TEXT       Model (fugu | fugu-ultra)
  -e, --effort CHOICE    Reasoning: high | xhigh | max
  --base-url TEXT        Override API base URL (for proxy / unofficial endpoints)
  -w, --web-search       Enable web search tool
  --no-viz              Disable visualization
  -v, --voice           Enable voice input
  -u, --unlimited       Unlimited prompt mode
```

### `submit` — Async Task Submission

```bash
fugu-vibe submit "Task Name" -p "Prompt..." [OPTIONS]

Options:
  -p, --prompt TEXT      Required: Task prompt
  -d, --description TEXT Task description
  -m, --model TEXT       Model override
  -e, --effort CHOICE    Reasoning effort
  -w, --web-search       Enable web search
  --depends-on TEXT      Task dependencies (multiple)
  -f, --files TEXT       Context files (multiple)
  --wait                 Wait for completion
  -u, --unlimited        Unlimited prompt mode

# Examples:
fugu-vibe submit "Refactor auth" -p "Refactor auth module..."
fugu-vibe submit "Write tests" -p "..." --depends-on <task-id>
fugu-vibe submit "Deep analysis" -p "..." --effort xhigh --wait
```

### `status` — Task Status

```bash
fugu-vibe status [TASK_ID] [OPTIONS]

Options:
  -w, --watch   Watch mode (auto-refresh)
  --json        Output as JSON

# Examples:
fugu-vibe status              # All tasks
fugu-vibe status <task-id>    # Specific task
fugu-vibe status -w           # Live monitoring
```

### `attach` — Attach to Running Task

```bash
fugu-vibe attach <task-id>
```

### `voice` — Voice Mode

```bash
fugu-vibe voice [OPTIONS]

Options:
  -c, --continuous   Continuous voice mode
  -w, --web-search   Enable web search
  -m, --model TEXT   Model override
  -e, --effort       Reasoning effort
```

### `config` — Configuration

```bash
fugu-vibe config show              # Show current config
fugu-vibe config init              # Create project config
fugu-vibe config init --global     # Create global config
fugu-vibe config set model.default fugu-ultra
fugu-vibe config path              # Show config file locations
```

## ⚙️ Configuration

Configuration hierarchy (highest priority first):
1. CLI flags
2. Environment variables (`FUGU_VIBE_*`)
3. Project config (`.fugu-vibe.toml`)
4. User config (`~/.config/fugu-vibe/config.toml`)
5. Defaults

### Example `.fugu-vibe.toml`

```toml
[api]
base_url = "https://api.sakana.ai/v1"
timeout = 7200
stream_idle_timeout_ms = 7200000

[model]
default = "fugu-ultra"
reasoning_effort = "xhigh"
max_output_tokens = 32768

[orchestration]
viz_mode = "full"
show_token_usage = true
infer_workers = true

[voice]
enabled = true
push_to_talk_key = "space"
silence_timeout = 2.0

[tasks]
max_parallel = 5
use_git_worktree = true
auto_merge = true

[prompt]
unlimited_mode = false
```

### Using a Proxy / Unofficial Base URL

You can route requests through a reverse proxy or unofficial endpoint:

**Via CLI flag (highest priority, per-command):**
```bash
fugu-vibe vibe --base-url https://your-proxy.com/v1
fugu-vibe submit "Task" -p "..." --base-url https://your-proxy.com/v1
```

**Via environment variable:**
```bash
export FUGU_VIBE_API_BASE_URL="https://your-proxy.com/v1"
export SAKANA_API_KEY="sk-your-key"
fugu-vibe vibe
```

**Via config file (persistent):**
```toml
[api]
base_url = "https://your-proxy.com/v1"
```

> ⚠️ **Note:** Do not commit API keys or `.fugu-vibe.toml` to version control. The project `.gitignore` already excludes them.

## 🧭 Orchestration Visualization

The dashboard shows Fugu's internal multi-agent coordination:

```
┌──────────────────────────────────────────────┐
│ 🐡 Fugu Ultra - Orchestration Dashboard      │
├──────────────────┬───────────────────────────┤
│ 🧭 Routing:      │ Output panel (live        │
│   gpt-5.5 (87%)  │ streaming content)        │
│                  │                           │
│ ⚡ Worker-1      │                           │
│   active         │                           │
│   (45 tok/s)     │                           │
│                  │                           │
│ 🔍 Verification  │                           │
│   #1             │                           │
├──────────────────┼───────────────────────────┤
│ 📥 Input: 3.2k   │ 📋 Tasks                  │
│ 📤 Output: 12.8k │ 🔄 Refactor auth [running]│
│ ⚙️  Orch: 8.4k   │ ⏳ Write tests [pending]  │
│ 📊 Total: 24.4k  │                           │
└──────────────────┴───────────────────────────┘
```

Since Fugu's API doesn't expose internal routing, the CLI uses **multi-signal inference**:
- Initial delays → routing decisions
- Token burst patterns → worker activation
- Content markers → parallel worker boundaries
- Token cost ratios → orchestration overhead

## 🎤 Voice Input

Voice mode uses:
- **VAD** (Voice Activity Detection) for auto-segmentation
- **Faster-Whisper** for local STT
- Push-to-talk with configurable key (default: Space)

```bash
# Install voice support
pip install fugu-vibe-cli[voice]

# Start voice session
fugu-vibe vibe --voice

# Or dedicated voice mode
fugu-vibe voice --continuous
```

## 🏗️ Architecture

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  CLI     │  │  Core    │  │   API    │  │ External │
│ (Click)  │  │  Engine  │  │  Layer   │  │  Svcs    │
├──────────┤  ├──────────┤  ├──────────┤  ├──────────┤
│ vibe     │  │ TaskMgr  │  │ FuguClient│  │ Sakana  │
│ submit   │  │ OrchViz  │  │ Request   │  │  API    │
│ status   │  │ EventBus │  │ Stream    │  │         │
│ voice    │  │ GitWT    │  │ Parser    │  │         │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └─────────┘
     │             │             │
┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐
│   TUI    │  │  Voice   │  │   Viz    │
│ (Rich)   │  │(Whisper) │  │(Timeline)│
└──────────┘  └──────────┘  └──────────┘
```

## 📚 Fugu API Specifics

This CLI handles Fugu's unique API behaviors:

| Parameter | Fugu Behavior | CLI Handling |
|-----------|--------------|--------------|
| `temperature` | Accepted but **ignored** | Logged warning |
| `parallel_tool_calls` | Accepted but **ignored** | Logged warning |
| `previous_response_id` | **Not accepted** | Full history sent |
| `reasoning.effort` | `high` / `xhigh` / `max` | Full support |
| `tools` | Built-in `web_search` | Enable with `--web-search` |
| `max_output_tokens` | Up to 32768 | Configurable |
| Orchestration tokens | 3rd token category | Tracked separately |

## 🔧 Development

```bash
# Clone
git clone https://github.com/fugu-vibe/fugu-vibe-cli.git
cd fugu-vibe-cli

# Install with uv (recommended)
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
mypy fugu_vibe/
```

### Known Issues & Fixes

| Issue | Fix |
|-------|-----|
| Python 3.14 `pyexpat` crash on macOS | Use Python 3.11–3.13 |
| `asyncio-subprocess-tee` not on PyPI | Removed from deps; using `asyncio.subprocess` |
| `api/__init__.py` import path error | Fixed: `fugu_vibe.request_builder` → `fugu_vibe.api.request_builder` |

## 📄 License

MIT License - see [LICENSE](LICENSE) file.

---

**Not affiliated with Sakana AI.** Fugu is a trademark of Sakana AI.
