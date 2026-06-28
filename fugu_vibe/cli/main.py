"""
Main CLI entry point for Fugu Vibe.

Commands:
    vibe      Start interactive vibe coding session
    submit    Submit a task asynchronously
    status    Show task status
    attach    Attach to a running task
    cancel    Cancel a task
    voice     Voice-controlled task submission
    config    Manage configuration
    models    List available models
    auth      Authentication management
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from fugu_vibe.config import Config, load_config

from fugu_vibe.cli.commands.vibe import vibe_command
from fugu_vibe.cli.commands.submit import submit_command
from fugu_vibe.cli.commands.status import status_command
from fugu_vibe.cli.commands.attach import attach_command
from fugu_vibe.cli.commands.cancel import cancel_command
from fugu_vibe.cli.commands.voice import voice_command
from fugu_vibe.cli.commands.config import config_command
from fugu_vibe.cli.commands.models import models_command
from fugu_vibe.cli.commands.auth import auth_command

logger = structlog.get_logger()
console = Console()


def print_banner() -> None:
    """Print the Fugu Vibe CLI banner."""
    banner = Text()
    banner.append("🐡 ", style="bold cyan")
    banner.append("Fugu Vibe CLI", style="bold white")
    banner.append("  v0.1.0", style="dim")
    banner.append("  — ", style="dim")
    banner.append("Vibe coding with Sakana Fugu", style="italic cyan")
    console.print(banner)
    console.print()


@click.group(invoke_without_command=True)
@click.option("--config", "config_path", type=click.Path(), help="Path to config file")
@click.option(
    "--workspace",
    "workspace_path",
    "-C",
    envvar="FUGU_VIBE_WORKSPACE",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Run commands from this workspace directory",
)
@click.option("--api-key", envvar="SAKANA_API_KEY", help="Sakana API key")
@click.option("--base-url", envvar="FUGU_VIBE_API_BASE_URL", help="Override API base URL for proxy/unofficial endpoints")
@click.option("--model", default=None, help="Default model (fugu | fugu-ultra)")
@click.option("--effort", type=click.Choice(["high", "xhigh", "max"]), help="Reasoning effort")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.version_option(version="0.1.0")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, workspace_path: Path | None,
        api_key: str | None, base_url: str | None, model: str | None,
        effort: str | None, verbose: bool) -> None:
    """
    🐡 Fugu Vibe CLI — Specialized vibe coding for Sakana Fugu.
    
    Features:
    • Async task execution with git-worktree isolation
    • Real-time orchestration visualization
    • Voice-controlled task submission
    • Unlimited prompt mode
    • Full Responses API support with all Fugu-specific parameters
    
    Get started:
        fugu-vibe auth login                    # Set up API key
        fugu-vibe vibe                          # Start interactive session
        fugu-vibe submit "Refactor auth" -p "..."  # Submit task
    """
    if workspace_path:
        workspace = workspace_path.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise click.ClickException(f"Workspace does not exist or is not a directory: {workspace}")
        os.chdir(workspace)

    # Load configuration from the selected workspace unless --config is provided.
    config = load_config(
        override_path=Path(config_path) if config_path else None
    )
    
    # Override with CLI options
    if api_key:
        config.api.api_key = api_key
    if base_url:
        config.api.base_url = base_url
    if model:
        config.model.default = model
    if effort:
        config.model.reasoning_effort = effort  # type: ignore
    
    # Store in context
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["verbose"] = verbose
    ctx.obj["workspace"] = Path.cwd()
    
    # Setup logging
    if verbose:
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(10),
        )
    
    # Print banner for top-level invocation
    if ctx.invoked_subcommand is None:
        print_banner()
        console.print("Run ", style="dim")
        console.print("fugu-vibe --help", style="bold cyan")
        console.print(" for available commands.", style="dim")
        console.print()
        console.print("Quick start:")
        console.print("  ", style="dim")
        console.print("fugu-vibe vibe", style="bold green")


# Register commands
cli.add_command(vibe_command, name="vibe")
cli.add_command(submit_command, name="submit")
cli.add_command(status_command, name="status")
cli.add_command(attach_command, name="attach")
cli.add_command(cancel_command, name="cancel")
cli.add_command(voice_command, name="voice")
cli.add_command(config_command, name="config")
cli.add_command(models_command, name="models")
cli.add_command(auth_command, name="auth")


def main() -> None:
    """Entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        if os.environ.get("FUGU_VIBE_DEBUG"):
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
