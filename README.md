# Fugu Vibe CLI

**English** | [中文](README.zh.md) | [日本語](README.ja.md)

A Python CLI for using Sakana Fugu-style APIs from a terminal. Built for heavy-duty development: it gives Fugu precise, structured tools, full-session persistence, and transparent orchestration-cost monitoring, while staying out of Fugu's internal multi-agent routing.

> Not affiliated with Sakana AI.

## Current Status

**Beta early stage.** All five deepening phases are implemented. The CLI can handle medium-to-heavy development tasks (5–15 files, 10 tool rounds, auto-test loops) and is ready for daily use.

- Text input: **production-ready**.
- PDF/image/file attachments: usable in `vibe` via `--file` or `/attach`.
- Workspace selection: usable via `-C/--workspace`.
- Session output: saved under `.fugu-vibe/sessions/` in the selected workspace.
- Async task status/output: saved under `.fugu-vibe/tasks/` in the selected workspace.
- Runtime workspace artifacts (`.fugu-vibe/` and `.fugu-worktrees/`) are ignored by git.
- **Orchestration dashboard**: optional via `--viz` or `fugu-vibe dashboard`; shows live token usage, orchestration ratio, and budget alerts.
- **Headless mode**: usable via `fugu-vibe run` for CI/SDK-style one-shot execution.
- **MCP integration**: stdio MCP servers can be registered and exposed through `mcp_list_tools` / `mcp_call`.
- **Voice mode**: full pipeline (VAD + Faster-Whisper STT + command parsing) is implemented. Push-to-talk and background voice interaction require manual trigger (`record_and_submit()`); continuous listening is not yet automated.

### What Fugu Vibe CLI does differently

Unlike general-purpose agent CLIs (Claude Code, OpenHands, Cline), this CLI is **not an outer orchestrator**. It does not plan, decompose, or verify tasks—that is Fugu's internal Conductor + TRINITY + Verifier. Instead, it provides **fine-grained, structured tools** so Fugu can execute precisely, and **state persistence** so long-running sessions survive disconnections.

- **15+ structured tools**: `file_edit` (old_string replacement), `file_write`, `file_read` (with line ranges), `file_search` (regex), `file_glob`, `file_delete`, `bash` (with safety classification), `git_status`, `git_diff`, `git_log`, `run_test`, `run_lint`, `mcp_list_tools`, `mcp_call`, etc.
- **All tool results return structured JSON** (exit_code, summary, failures, duration) so Fugu's Verifier can assess them instantly.
- **Auto-test loop**: after `file_edit` or `file_write`, the CLI automatically runs `run_test` and injects the structured result back into the conversation. If tests fail, Fugu sees the failure JSON and can fix it in the next round.
- **Diff preview before write**: in `ask` mode, every file edit or write shows a `git diff` style preview (`---` / `+++` / `+` / `-`) before the user confirms.
- **Safety & governance**: four permission modes (`ask`, `auto-safe`, `auto-edit`, `auto`), command risk classification, sensitive-path blocking, and git-based checkpoints with `/undo` rollback.
- **Context assembly**: `CodebaseIndex` builds a lightweight file-tree + symbol summary so Fugu's Conductor can choose which files to read.
- **Session persistence**: full conversation history is saved as JSONL after every round; disconnections are detected and reconnected with exponential backoff.
- **Orchestration cost monitoring**: real-time token budget tracking, orchestration-ratio alerts, and cost estimates.
- **Fugu-specific optimizations**: adaptive `effort` selection (high/xhigh/max), `instructions` template system (`.fugu/instructions.md`), and `unlimited_mode` safety enforcement.

## Install

Requires Python 3.12+ (uses `from __future__ import annotations` and `|` union types).

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

Optional voice dependencies:

```bash
uv pip install -e ".[voice]"
# or: pip install pyaudio webrtcvad faster-whisper
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
- Use `/checkpoint` to manually save a git-based checkpoint.
- Use `/undo` to roll back to the last checkpoint.
- Use `/help` to show session commands.
- Use `/quit`, `/q`, `/exit`, `Ctrl+C`, or `Ctrl+D` to exit.

Useful options:

```bash
fugu-vibe vibe --model fugu-ultra --effort xhigh
fugu-vibe vibe --web-search
fugu-vibe vibe --file spec.pdf --file screenshot.png
fugu-vibe vibe --unlimited
fugu-vibe vibe --safety ask           # ask before every write/execute
fugu-vibe vibe --safety auto-safe    # auto-run safe commands, ask for risky ones
```

Attach files during a session:

```text
/attach spec.pdf
/attach screenshot.png notes.txt
/files
/clear-files
```

Attachments are sent with each prompt until you clear them. Images are sent as image inputs; PDFs and other files are sent as file inputs. Small text/code files are inlined as text context. Attachments larger than 25 MB are rejected before sending.

Session transcripts are written to:

```text
.fugu-vibe/sessions/<timestamp>.md
```

Current context metadata is written to:

```text
.fugu-vibe/context/current.json
```

Workspace file inspection commands are read-only and constrained to the selected workspace. They skip runtime/cache directories such as `.git/`, `.fugu-vibe/`, `.venv/`, and `node_modules/`.

The interactive session can execute Fugu function calls for workspace file, terminal, git, and MCP bridge tools when those tool groups are enabled by policy. The model can auto-call `file_edit`, `file_write`, `bash`, `run_test`, `git_status`, etc., based on the current permission mode.

### Terminal execution safety

Terminal execution is disabled by default. To enable it in `vibe`, set:

```toml
[tools]
terminal_enabled = true
terminal_approval = "ask"
```

Then use:

```text
/tools
/terminal git status
/terminal python -m pytest -q
```

The terminal tool is constrained to the workspace, blocks common destructive command patterns (`rm -rf`, `sudo`, `curl | sh`), applies a timeout, truncates displayed output, and saves full logs under `.fugu-vibe/tool-runs/`.

Safe validation commands such as `run_test` can run automatically after successful edits when `[tools] auto_test_after_edit = true`.

### Patch application policy

Patch application defaults to `ask-apply`. `/apply <patch-file>` validates patch paths, runs `git apply --check`, shows the diff, and asks for `yes` before applying. Set `[patch] mode = "propose-only"` to disable applying patches from the CLI.

## Headless Runs, MCP, and SDK

Run one prompt without entering the interactive prompt:

```bash
fugu-vibe run "Summarize this repository"
fugu-vibe run --script task.md --json
```

`--json` returns a structured result with `ok`, `content`, `tool_calls`, `rounds`, and selected `effort`, which is useful for CI or SDK-style integrations.

Register stdio MCP servers per workspace:

```bash
fugu-vibe mcp add filesystem python path/to/server.py
fugu-vibe mcp list
fugu-vibe mcp tools filesystem
```

When MCP is enabled, Fugu can discover server tools through `mcp_list_tools` and call them through `mcp_call`. MCP configuration is stored under `.fugu-vibe/mcp.json` and is ignored by git.

```toml
[mcp]
enabled = true
timeout_seconds = 30
```

Python SDK entry point:

```python
from fugu_vibe.core.headless import run_headless

result = await run_headless(
    prompt="Refactor auth.py",
    workspace="/path/to/project",
    model="fugu-ultra",
    effort="xhigh",
    json_output=True,
)
```

## Working In A Specific Workspace

Use `-C/--workspace` before the subcommand:

```bash
fugu-vibe -C /path/to/project vibe
```

This changes the process working directory before loading project config and before initializing git/worktree handling. It affects commands such as `vibe`, `submit`, `run`, and `config`.

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

Task records are stored in `.fugu-vibe/tasks/`. Tasks record Fugu output and metadata, and automatically apply code changes when the model calls `file_edit` or `file_write` under the current safety policy.

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

[tools]
max_tool_rounds = 10
auto_test_after_edit = true
auto_test_command = "python -m pytest -q"
auto_compile_after_edit = true
terminal_enabled = true
terminal_approval = "ask"

[safety]
mode = "ask"               # ask | auto-safe | auto-edit | auto
command_timeout_seconds = 30

[patch]
mode = "ask-apply"
```

Do not commit API keys or local config containing secrets.

## Project Instructions Template

Create `.fugu/instructions.md` in your project root to give Fugu's internal Conductor project-specific context (architecture, conventions, testing strategy). This affects how Fugu routes tasks among its internal agents.

```markdown
---
project_type: python-backend
framework: fastapi
conventions:
  - Use type hints everywhere
  - Prefer pydantic models for validation
  - Tests go in tests/ mirroring src/ structure
---

# Project Context

This is a Python backend API using FastAPI + SQLAlchemy + Alembic.

## Architecture
- `src/api/` - Route handlers
- `src/services/` - Business logic
- `src/models/` - Pydantic + SQLAlchemy models
- `src/db/` - Database layer
- `tests/` - Pytest test suite
```

## Orchestration Dashboard

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

The two-terminal dashboard reads `.fugu-vibe/events.jsonl` in the selected workspace. It shows:

- Live token usage (Input / Output / Orchestration)
- Orchestration ratio with color-coded alerts
- Budget progress bar and cost estimate
- Fugu internal stage inference (routing / worker / verification / synthesis)
- Checkpoint history and rollback status

## Voice Mode

Voice mode is implemented as a full pipeline: **VAD (Voice Activity Detection) → Faster-Whisper local STT → natural-language command parsing → text prompt submission**.

Manual trigger (current default):

```python
from fugu_vibe.voice.pipeline import VoicePipeline
pipeline = VoicePipeline(workspace="/path/to/project")
result = await pipeline.record_and_submit()
```

CLI commands (experimental):

```bash
fugu-vibe vibe --voice
fugu-vibe voice --continuous
```

Continuous background listening is not yet automated. The `voice --continuous` command starts the pipeline but waits for manual trigger events.

## Development

Default CLI output is kept quiet. Use `--verbose` before the subcommand to show debug logs:

```bash
fugu-vibe --verbose vibe
```

Run the test suite:

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

pytest
python -m ruff check .
mypy fugu_vibe/
```

## License

MIT License.
