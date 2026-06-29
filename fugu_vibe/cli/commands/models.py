"""
`fugu-vibe models` - List available Fugu models.
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from fugu_vibe.api.client import FuguClient

console = Console()


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def models_command(ctx: click.Context, as_json: bool) -> None:
    """
    📋 List available Fugu models and their capabilities.

    Shows model information from Sakana API including:
    - Model slugs (fugu, fugu-ultra)
    - Reasoning effort levels
    - Context window sizes
    - Supported features

    Examples:
        fugu-vibe models
        fugu-vibe models --json
    """
    config = ctx.obj["config"]
    asyncio.run(_list_models(config, as_json))


async def _list_models(config, as_json: bool) -> None:
    client = FuguClient(config)

    try:
        models = await client.get_models()

        if as_json:
            import json
            console.print(json.dumps(models, indent=2))
            return

        console.print("\n[bold cyan]📋 Available Fugu Models[/bold cyan]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Model")
        table.add_column("Slug")
        table.add_column("Context Window")
        table.add_column("Reasoning Levels")
        table.add_column("Features")

        # Built-in models (always shown)
        table.add_row(
            "Fugu",
            "fugu",
            "1,000,000",
            "high, xhigh",
            "Multi-agent routing, fast",
            style="green",
        )
        table.add_row(
            "Fugu Ultra",
            "fugu-ultra",
            "1,000,000",
            "high, xhigh",
            "Deep multi-agent, 1-3 agents",
            style="bold cyan",
        )

        # API-returned models
        for model in models:
            slug = model.get("id", "unknown")
            if slug not in ("fugu", "fugu-ultra"):
                table.add_row(
                    model.get("name", slug),
                    slug,
                    f"{model.get('context_window', '?'):,}" if isinstance(model.get('context_window'), int) else "?",
                    ", ".join(model.get("reasoning_levels", [])),
                    ", ".join(model.get("features", [])),
                )

        console.print(table)

        # Reasoning effort explanation
        console.print("\n[bold]Reasoning Effort Levels:[/bold]")
        console.print("  [green]high[/green]  - Deep reasoning for complex problems")
        console.print("  [cyan]xhigh[/cyan] - Maximum reasoning (alias: max)")

        console.print("\n[bold]Key Differences:[/bold]")
        console.print("  [green]fugu[/green]       - Routes to best model per task, lower latency")
        console.print("  [cyan]fugu-ultra[/cyan]   - Coordinates 1-3 expert agents, higher quality")

    except Exception as e:
        console.print(f"[yellow]Could not fetch models from API: {e}[/yellow]")
        console.print("[dim]Showing built-in model information.[/dim]")

        # Show built-in info even on API error
        console.print("\n[bold cyan]📋 Fugu Models[/bold cyan]\n")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Model")
        table.add_column("Slug")
        table.add_column("Context")
        table.add_column("Reasoning")
        table.add_column("Description")

        table.add_row("Fugu", "fugu", "1M", "high, xhigh",
                     "Routes to best model per task")
        table.add_row("Fugu Ultra", "fugu-ultra", "1M", "high, xhigh",
                     "Coordinates 1-3 expert agents")

        console.print(table)
    finally:
        await client.close()
