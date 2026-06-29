"""
`fugu-vibe cancel` - Cancel a running or pending task.
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console

from fugu_vibe.api.client import FuguClient
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.task_manager import TaskManager

console = Console()


@click.command()
@click.argument("task_id")
@click.option("--all", "cancel_all", is_flag=True, help="Cancel all tasks")
@click.pass_context
def cancel_command(ctx: click.Context, task_id: str, cancel_all: bool) -> None:
    """
    🛑 Cancel a running or pending task.

    Examples:
        fugu-vibe cancel <task-id>
        fugu-vibe cancel --all
    """
    config = ctx.obj["config"]
    asyncio.run(_cancel(config, task_id, cancel_all))


async def _cancel(config, task_id: str, cancel_all: bool) -> None:
    event_bus = EventBus()
    client = FuguClient(config)
    task_manager = TaskManager(config, client, event_bus)
    await task_manager.start()

    try:
        if cancel_all:
            status = await task_manager.status()
            cancelled = 0
            for task in status.get("tasks", []):
                if task.get("status") in ("pending", "queued", "running") and await task_manager.cancel(task["task_id"]):
                    cancelled += 1
            console.print(f"[yellow]Cancelled {cancelled} tasks[/yellow]")
        else:
            if await task_manager.cancel(task_id):
                console.print(f"[green]✅ Task {task_id} cancelled[/green]")
            else:
                console.print(f"[red]❌ Could not cancel {task_id}[/red]")
                console.print("[dim]Task may already be completed or not found.[/dim]")
    finally:
        await task_manager.close()
        await client.close()
