# Fugu Vibe CLI

**English** | [中文](README.zh.md) | [日本語](README.ja.md)

A Python CLI for using Sakana Fugu-style APIs from a terminal. It provides an interactive prompt, optional orchestration visualization, project workspace selection, async task submission, and Fugu-specific request handling.

> Not affiliated with Sakana AI.

## Current Status

This project is early-stage. The stable path is the normal text-based `vibe` session.

- Text input: usable.
- Workspace selection: usable via `-C/--workspace`.
- Orchestration dashboard: optional via `--viz`; disabled by default because full-screen rendering can interfere with terminal input.
- Voice mode: placeholder only. The recorder/STT scaffolding exists, but push-to-talk/background voice interaction is not fully implemented yet.

## Install

Use Python 3.11-3.13. Python 3.14 may hit dependency/runtime issues on macOS.

```bash
git clone https://github.com/fugu-vibe/fugu-vibe-cli.git
cd fugu-vibe-cli

# Recommended
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .

# Or with pip inside your own virtualenv
pip install -e .
```

## Authentication

```bash
export SAKANA_API_KEY="your-key"
```

Or save it through the CLI:

```bash
fugu-vibe auth login
fugu-vibe auth status
```

If you use a proxy or unofficial compatible endpoint:

```bash
export FUGU_VIBE_API_BASE_URL="https://your-proxy.example/v1"
```

or pass it per command:

```bash
fugu-vibe --base-url https://your-proxy.example/v1 vibe
```

## Interactive Use

Start a stable text session:

```bash
fugu-vibe vibe
```

Inside the session:

- Type a prompt and press Enter.
- Use `/status` to show task status.
- Use `/tasks` to list active tasks.
- Use `/help` to show session commands.
- Use `/quit`, `/q`, `/exit`, `Ctrl+C`, or `Ctrl+D` to exit.

Useful options:

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --unlimited
```

Enable the dashboard only when you want it:

```bash
fugu-vibe vibe --viz
```

## Working In A Specific Workspace

Use `-C/--workspace` before the subcommand:

```bash
fugu-vibe -C /path/to/project vibe
```

This changes the process working directory before loading project config and before initializing git/worktree handling. It affects commands such as `vibe`, `submit`, and `config`.

You can also set it with an environment variable:

```bash
export FUGU_VIBE_WORKSPACE="/path/to/project"
fugu-vibe vibe
```

## Async Tasks

Submit a task:

```bash
fugu-vibe submit "Refactor auth" -p "Refactor the authentication module"
```

Wait for completion:

```bash
fugu-vibe submit "Analyze code" -p "Review the codebase" --wait
```

Use dependencies:

```bash
fugu-vibe submit "Write tests" -p "Add tests" --depends-on <task-id>
```

Check status:

```bash
fugu-vibe status
fugu-vibe status <task-id>
fugu-vibe status --watch
```

Attach or cancel:

```bash
fugu-vibe attach <task-id>
fugu-vibe cancel <task-id>
```

## Configuration

Config is loaded in this order, from highest to lowest priority:

1. CLI flags
2. Environment variables
3. Project config: `.fugu-vibe.toml`
4. User config: `~/.config/fugu-vibe/config.toml`
5. Defaults

Create or inspect config:

```bash
fugu-vibe config init
fugu-vibe config init --global
fugu-vibe config show
fugu-vibe config path
fugu-vibe config set model.default fugu-ultra
```

Example `.fugu-vibe.toml`:

```toml
[api]
base_url = "https://api.sakana.ai/v1"
timeout = 7200
stream_idle_timeout_ms = 7200000

[model]
default = "fugu-ultra"
reasoning_effort = "xhigh"
max_output_tokens = 32768

[tasks]
max_parallel = 5
use_git_worktree = true
auto_merge = true

[prompt]
unlimited_mode = false
```

Do not commit API keys or local config containing secrets.

## Voice Mode

Voice mode is currently a placeholder. The code contains recorder/STT scaffolding, but full push-to-talk and continuous voice interaction are not production-ready.

These commands may exist, but should not be treated as stable:

```bash
fugu-vibe vibe --voice
fugu-vibe voice --continuous
```

## Development

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest
ruff check .
mypy fugu_vibe/
```

## License

MIT License.
