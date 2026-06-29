"""
`fugu-vibe auth` - Authentication management.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Prompt

console = Console()


@click.group()
def auth_command() -> None:
    """🔐 Manage Sakana API authentication."""
    pass


@auth_command.command(name="login")
def auth_login() -> None:
    """Set up API key authentication."""
    console.print("\n[bold cyan]🔐 Sakana API Authentication[/bold cyan]\n")
    console.print("Get your API key from: https://console.sakana.ai/api-keys\n")

    api_key = Prompt.ask("Enter your Sakana API key", password=True)
    api_key = api_key.strip()

    if not api_key:
        console.print("[red]❌ API key cannot be empty[/red]")
        return

    # Store in shell config
    shell_files = {
        "bash": Path.home() / ".bashrc",
        "zsh": Path.home() / ".zshrc",
        "fish": Path.home() / ".config" / "fish" / "config.fish",
    }

    # Detect shell
    shell = os.environ.get("SHELL", "").split("/")[-1]

    if shell in shell_files:
        rc_file = shell_files[shell]
        rc_file.parent.mkdir(parents=True, exist_ok=True)

        # Add to RC file if not already present
        marker = "# Fugu Vibe CLI - Sakana API Key"
        export_line = f'export SAKANA_API_KEY="{api_key}"'

        existing = rc_file.read_text() if rc_file.exists() else ""

        if "SAKANA_API_KEY" in existing:
            # Update existing
            lines = existing.split("\n")
            new_lines = []
            skip_block = False
            for line in lines:
                if line.strip() == marker:
                    skip_block = True
                    continue
                if skip_block and line.startswith("export SAKANA_API_KEY"):
                    skip_block = False
                    continue
                if skip_block and not line.strip():
                    skip_block = False
                if not skip_block:
                    new_lines.append(line)

            existing = "\n".join(new_lines)

        # Append new entry
        with open(rc_file, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(f"\n{marker}\n")
            f.write(f"{export_line}\n")

        console.print(f"[green]✅ API key saved to {rc_file}[/green]")
        console.print(f"[dim]Run `source {rc_file}` to apply, or restart your terminal.[/dim]")
    else:
        # Unknown shell - just print the export
        console.print("\n[yellow]Add this to your shell configuration:[/yellow]")
        console.print(f"[bold]export SAKANA_API_KEY=\"{api_key[:10]}...\"[/bold]")

    # Also set for current session
    os.environ["SAKANA_API_KEY"] = api_key
    console.print("\n[green]✅ API key set for current session[/green]")


@auth_command.command(name="status")
def auth_status() -> None:
    """Check authentication status."""
    api_key = os.environ.get("SAKANA_API_KEY", "")

    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        console.print("[green]✅ Authenticated[/green]")
        console.print(f"   API Key: {masked}")

        # Check if also in config files
        for name, path in [
            (".bashrc", Path.home() / ".bashrc"),
            (".zshrc", Path.home() / ".zshrc"),
        ]:
            if path.exists() and "SAKANA_API_KEY" in path.read_text():
                console.print(f"   Saved in: ~/{name}")
                break
    else:
        console.print("[red]❌ Not authenticated[/red]")
        console.print("\nRun: [bold]fugu-vibe auth login[/bold]")


@auth_command.command(name="logout")
def auth_logout() -> None:
    """Remove stored API key."""
    # Remove from environment
    if "SAKANA_API_KEY" in os.environ:
        del os.environ["SAKANA_API_KEY"]

    # Remove from shell configs
    removed = False
    for name, path in [
        (".bashrc", Path.home() / ".bashrc"),
        (".zshrc", Path.home() / ".zshrc"),
        ("config.fish", Path.home() / ".config" / "fish" / "config.fish"),
    ]:
        if path.exists() and "SAKANA_API_KEY" in path.read_text():
            content = path.read_text()
            lines = content.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if "# Fugu Vibe CLI" in line:
                    skip = True
                    continue
                if skip and "SAKANA_API_KEY" in line:
                    skip = False
                    continue
                if skip and not line.strip():
                    skip = False
                    continue
                new_lines.append(line)

            path.write_text("\n".join(new_lines))
            removed = True
            console.print(f"[green]✅ Removed from ~/{name}[/green]")

    if removed:
        console.print("\n[yellow]Restart your terminal for changes to take effect.[/yellow]")
    else:
        console.print("[green]✅ Logged out[/green]")
