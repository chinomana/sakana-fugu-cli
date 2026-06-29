"""
`fugu-vibe status` - Show task and system status.
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from fugu_vibe.api.client import FuguClient
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.task_manager import TaskManager

console = Console()


@click.command()
@click.argument("task_id", required=False)
@click.option("--watch", "-w", is_flag=True, help="Watch mode (auto-refresh)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status_command(ctx: click.Context, task_id: str | None, watch: bool, as_json: bool) -> None:
    """
    📊 Show task status and system overview.

    Examples:
        fugu-vibe status              # Show all tasks
        fugu-vibe status <task-id>    # Show specific task
        fugu-vibe status -w           # Watch mode
    """
    config = ctx.obj["config"]

    if watch:
        asyncio.run(_watch_status(config, task_id, as_json))
    else:
        asyncio.run(_show_status(config, task_id, as_json))


async def _show_status(config, task_id: str | None, as_json: bool) -> None:
    event_bus = EventBus()
    client = FuguClient(config)
    task_manager = TaskManager(config, client, event_bus)
    await task_manager.start()

    try:
        status = await task_manager.status(task_id)

        if as_json:
            import json
            console.print(json.dumps(status, indent=2, default=str))
            return

        if task_id:
            # Single task detail
            _print_task_detail(status)
        else:
            # Overview
            _print_overview(status)

    finally:
        await task_manager.close()
        await client.close()


async def _watch_status(config, task_id: str | None, as_json: bool) -> None:
    """Watch mode with auto-refresh."""

    with console.screen():
        while True:
            console.clear()
            await _show_status(config, task_id, as_json)
            console.print("\n[dim]Refreshing every 2s (Ctrl+C to exit)[/dim]")
            try:
                await asyncio.sleep(2)
            except KeyboardInterrupt:
                break


def _print_overview(status: dict) -> None:
    """Print system overview."""
    console.print("\n[bold cyan]📊 Task Overview[/bold cyan]\n")

    # Summary
    tasks = status.get("tasks", [])
    running = sum(1 for t in tasks if t.get("status") == "running")
    completed = sum(1 for t in tasks if t.get("status") in ("completed", "merged"))
    failed = sum(1 for t in tasks if t.get("status") == "failed")
    pending = sum(1 for t in tasks if t.get("status") in ("pending", "queued"))

    summary = Table(show_header=False, box=None)
    summary.add_column("Metric", style="bold")
    summary.add_column("Value")
    summary.add_row("Total Tasks", str(len(tasks)))
    summary.add_row("🔄 Running", str(running))
    summary.add_row("⏳ Pending", str(pending))
    summary.add_row("✅ Completed", str(completed))
    summary.add_row("❌ Failed", str(failed))
    summary.add_row("📊 Max Parallel", str(status.get("max_parallel", "-")))
    console.print(summary)

    if tasks:
        console.print("\n[bold]Tasks:[/bold]")
        table = Table(show_header=True)
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Model")
        table.add_column("Duration")

        for task in tasks:
            status_color = {
                "running": "yellow",
                "completed": "green",
                "failed": "red",
                "pending": "dim",
                "queued": "blue",
                "merged": "cyan",
            }.get(task.get("status", ""), "white")

            table.add_row(
                task.get("task_id", "")[:12],
                task.get("name", ""),
                f"[{status_color}]{task.get('status', '-')}[/]",
                task.get("model", ""),
                f"{task.get('duration', 0):.1f}s" if task.get("duration") else "-",
            )

        console.print(table)


def _print_task_detail(task: dict) -> None:
    """Print detailed task information."""
    if "error" in task:
        console.print(f"[red]Error: {task['error']}[/red]")
        return

    console.print(f"\n[bold cyan]📋 {task.get('name', 'Task')}[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("ID", task.get("task_id", "-"))
    table.add_row("Status", task.get("status", "-"))
    table.add_row("Model", task.get("model", "-"))
    table.add_row("Effort", task.get("effort", "-"))
    table.add_row("Branch", task.get("branch", "-"))
    table.add_row("Worktree", task.get("worktree", "-"))

    if task.get("duration"):
        table.add_row("Duration", f"{task['duration']:.1f}s")

    deps = task.get("depends_on", [])
    table.add_row("Dependencies", ", ".join(deps) if deps else "None")

    console.print(table)

    if task.get("output"):
        console.print("\n[bold]Output:[/bold]")
        console.print(task["output"][:2000])
        if len(task["output"]) > 2000:
            console.print("[dim]... (truncated)[/dim]")

    if task.get("error"):
        console.print(f"\n[red]Error: {task['error']}[/red]")
