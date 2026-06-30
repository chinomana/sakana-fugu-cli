"""
`fugu-vibe config` - Manage CLI configuration.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.syntax import Syntax

from fugu_vibe.config import Config, load_config

console = Console()


@click.group()
def config_command() -> None:
    """⚙️  Manage Fugu Vibe CLI configuration."""
    pass


@config_command.command(name="show")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def config_show(ctx: click.Context, as_json: bool) -> None:
    """Show current configuration."""
    config = ctx.obj.get("config") if ctx.obj else None
    config = config or load_config()

    if as_json:
        import json

        console.print(json.dumps(config.model_dump(), indent=2))
        return

    toml_content = _generate_config_toml(config)
    syntax = Syntax(toml_content, "toml", theme="monokai", line_numbers=True)
    console.print(syntax)


@config_command.command(name="init")
@click.option("--global", "global_config", is_flag=True, help="Create global config")
def config_init(global_config: bool) -> None:
    """Initialize configuration file."""
    config = Config()

    if global_config:
        path = Path.home() / ".config" / "fugu-vibe" / "config.toml"
    else:
        path = Path.cwd() / ".fugu-vibe.toml"

    path.parent.mkdir(parents=True, exist_ok=True)

    toml_content = _generate_config_toml(config)
    path.write_text(toml_content)

    console.print(f"[green]✅ Config created at {path}[/green]")


@config_command.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value."""
    config = load_config()

    # Navigate nested keys (e.g., "model.default")
    parts = key.split(".")
    target = config
    for part in parts[:-1]:
        target = getattr(target, part)

    # Set value with type conversion
    attr_name = parts[-1]
    current = getattr(target, attr_name)

    if isinstance(current, bool):
        new_value = value.lower() in ("true", "1", "yes")
    elif isinstance(current, int):
        new_value = int(value)
    elif isinstance(current, float):
        new_value = float(value)
    else:
        new_value = value

    setattr(target, attr_name, new_value)

    # Save
    path = Path.cwd() / ".fugu-vibe.toml"
    if not path.exists():
        path = Path.home() / ".config" / "fugu-vibe" / "config.toml"

    config.to_file(path)
    console.print(f"[green]✅ Set {key} = {new_value}[/green]")


@config_command.command(name="path")
def config_path() -> None:
    """Show configuration file locations."""
    paths = [
        ("Project", Path.cwd() / ".fugu-vibe.toml"),
        ("User", Path.home() / ".config" / "fugu-vibe" / "config.toml"),
    ]

    console.print("\n[bold]Configuration files:[/bold]")
    for name, path in paths:
        exists = "✅" if path.exists() else "❌"
        console.print(f"  {exists} [{name}] {path}")


def _generate_config_toml(config: Config) -> str:
    """Generate TOML configuration string."""
    return f"""# Fugu Vibe CLI Configuration
# Documentation: https://fugu-vibe-cli.readthedocs.io

[api]
base_url = "{config.api.base_url}"
timeout = {config.api.timeout}
max_retries = {config.api.max_retries}
stream = {str(config.api.stream).lower()}
stream_idle_timeout_ms = {config.api.stream_idle_timeout_ms}
stream_max_retries = {config.api.stream_max_retries}
request_max_retries = {config.api.request_max_retries}
# api_key = "set via SAKANA_API_KEY env var"

[model]
default = "{config.model.default}"
reasoning_effort = "{config.model.reasoning_effort}"
max_output_tokens = {config.model.max_output_tokens}
truncation = "{config.model.truncation}"

[orchestration]
viz_mode = "{config.orchestration.viz_mode}"
show_token_usage = {str(config.orchestration.show_token_usage).lower()}
show_routing_decisions = {str(config.orchestration.show_routing_decisions).lower()}
infer_workers = {str(config.orchestration.infer_workers).lower()}
heartbeat_interval = {config.orchestration.heartbeat_interval}

[voice]
enabled = {str(config.voice.enabled).lower()}
engine = "{config.voice.engine}"
model = "{config.voice.model}"
language = "{config.voice.language}"
push_to_talk_key = "{config.voice.push_to_talk_key}"
vad_aggressiveness = {config.voice.vad_aggressiveness}
auto_submit = {str(config.voice.auto_submit).lower()}
silence_timeout = {config.voice.silence_timeout}
min_recording_duration = {config.voice.min_recording_duration}

[tasks]
max_parallel = {config.tasks.max_parallel}
use_git_worktree = {str(config.tasks.use_git_worktree).lower()}
auto_merge = {str(config.tasks.auto_merge).lower()}
timeout = {config.tasks.timeout}
git_default_branch = "{config.tasks.git_default_branch}"

[prompt]
unlimited_mode = {str(config.prompt.unlimited_mode).lower()}
custom_instructions = "{config.prompt.custom_instructions or ""}"

[tools]
terminal_enabled = {str(config.tools.terminal_enabled).lower()}
terminal_approval = "{config.tools.terminal_approval}"
terminal_timeout_seconds = {config.tools.terminal_timeout_seconds}
max_output_chars = {config.tools.max_output_chars}
max_tool_rounds = {config.tools.max_tool_rounds}
auto_test_after_edit = {str(config.tools.auto_test_after_edit).lower()}
auto_test_command = "{config.tools.auto_test_command}"
auto_compile_after_edit = {str(config.tools.auto_compile_after_edit).lower()}
auto_lint_after_edit = {str(config.tools.auto_lint_after_edit).lower()}
auto_lint_command = "{config.tools.auto_lint_command}"

[patch]
mode = "{config.patch.mode}"
"""
