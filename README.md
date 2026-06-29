# Fugu Vibe CLI

**English** | [中文](README.zh.md) | [日本語](README.ja.md)

A Python CLI for using Sakana Fugu-style APIs from a terminal. It provides an interactive prompt, optional orchestration visualization, project workspace selection, async task submission, and Fugu-specific request handling.

> Not affiliated with Sakana AI.

## Current Status

This project is early-stage. The stable path is the normal text-based `vibe` session.

- Text input: usable.
- PDF/image/file attachments: usable in `vibe` via `--file` or `/attach`.
- Workspace selection: usable via `-C/--workspace`.
- Session output: saved under `.fugu-vibe/sessions/` in the selected workspace.
- Async task status/output: saved under `.fugu-vibe/tasks/` in the selected workspace.
- Runtime workspace artifacts under `.fugu-vibe/` and `.fugu-worktrees/` are ignored by git.
- Orchestration dashboard: optional via `--viz`; disabled by default because full-screen rendering can interfere with terminal input.
- Voice mode: placeholder only. The recorder/STT scaffolding exists, but push-to-talk/background voice interaction is not fully implemented yet.

This CLI sends prompts and file context to Fugu and records the output. It does not yet automatically apply model-generated patches to your source tree.

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
- Use `/context` to inspect current prompt context.
- Use `/compact` to compact older conversation turns into a local summary.
- Use `/ls [glob]`, `/read <path>`, and `/search <query> [glob]` to inspect workspace files safely.
- Use `/diff` to inspect current git diff.
- Use `/apply <patch-file>` to check and apply a unified diff under the configured patch policy.
- Use `/tools` to inspect local tool policy.
- Use `/terminal <command>` to run a workspace terminal command only when terminal tools are explicitly enabled.
- Use `/attach <path>` to add PDF/image/file context.
- Use `/files` and `/clear-files` to inspect or clear attached files.
- Use `/status` to show task status.
- Use `/tasks` to list active tasks.
- Use `/help` to show session commands.
- Use `/quit`, `/q`, `/exit`, `Ctrl+C`, or `Ctrl+D` to exit.

Useful options:

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --file spec.pdf --file screenshot.png
fugu-vibe vibe --unlimited
```

Attach files during a session:

```text
/attach spec.pdf
/attach screenshot.png notes.txt
/files
/clear-files
```

Attachments are sent with each prompt until you clear them. Images are sent as image inputs; PDFs and other files are sent as file inputs.
Small text/code files are inlined as text context. Attachments larger than 25 MB are rejected before sending.

Session transcripts are written to:

```text
.fugu-vibe/sessions/<timestamp>.md
```

Current context metadata is written to:

```text
.fugu-vibe/context/current.json
```

Workspace file inspection commands are read-only and constrained to the selected workspace. They skip runtime/cache directories such as `.git/`, `.fugu-vibe/`, `.venv/`, and `node_modules/`.

The interactive session can execute Fugu function calls for workspace file tools (`file_list`, `file_read`, `file_search`, `file_mkdir`, `file_write`). Terminal execution is not exposed for automatic model calls.

Terminal execution is disabled by default. To enable manual terminal runs in `vibe`, set:

```toml
[tools]
terminal_enabled = true
terminal_approval = "ask"
```

Then use:

```text
/tools
/terminal git status
```

The terminal tool is constrained to the workspace, blocks common destructive command patterns, applies a timeout, truncates displayed output, and saves full logs under `.fugu-vibe/tool-runs/`. Fugu does not yet invoke terminal tools automatically.

Patch application defaults to `ask-apply`. `/apply <patch-file>` validates patch paths, runs `git apply --check`, shows the diff, and asks for `yes` before applying. Set `[patch] mode = "propose-only"` to disable applying patches from the CLI.

Enable the dashboard only when you want it:

```bash
fugu-vibe vibe --viz
```

You can also keep `vibe` in one terminal and open the dashboard in another terminal for the same workspace:

```bash
# Terminal 1: work normally
fugu-vibe -C /path/to/project vibe

# Terminal 2: watch the dashboard for that workspace
fugu-vibe -C /path/to/project dashboard
```

The two-terminal dashboard reads `.fugu-vibe/events.jsonl` in the selected workspace. It only shows events produced after `vibe` starts.

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

Include files as context:

```bash
fugu-vibe submit "Review spec" -p "Summarize this spec" -f spec.pdf --wait
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

Task records are stored in `.fugu-vibe/tasks/`. Tasks record Fugu output and metadata, but do not automatically apply code changes to the workspace yet.

`submit` currently keeps the submitting process alive while queued/running tasks execute. Use `--wait` when you want the command to print the final result in the same terminal.

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

Default CLI output is kept quiet. Use `--verbose` before the subcommand to show debug logs:

```bash
fugu-vibe --verbose vibe
```

Local terminal tools are disabled by default. Patch application policy defaults to `ask-apply`; future patch tooling should show a diff and ask before modifying files.

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
