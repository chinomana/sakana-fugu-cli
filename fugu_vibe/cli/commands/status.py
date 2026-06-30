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
    summary.add_row("🎛️ Active Slots", f"{status.get('running', 0)}/{status.get('max_parallel', '-')}")
    if status.get("scheduled_waiting"):
        summary.add_row("🕓 Scheduled Waiting", str(status["scheduled_waiting"]))

    summary.add_row("📊 Max Parallel", str(status.get("max_parallel", "-")))
    console.print(summary)

    if tasks:
        console.print("\n[bold]Tasks:[/bold]")
        table = Table(show_header=True)
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Model")
        table.add_column("Rounds", justify="right")
        table.add_column("Tools", justify="right")
        table.add_column("Tokens", justify="right")
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
                str(task.get("rounds") or "-"),
                str(task.get("tool_call_count") or "-"),
                _format_tokens(task.get("token_usage", {})),
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
    table.add_row("Rounds", str(task.get("rounds") or 0))
    table.add_row("Tool Calls", str(task.get("tool_call_count") or 0))
    tokens = task.get("token_usage", {})
    table.add_row("Tokens", _format_tokens(tokens, detailed=True))
    orchestration = task.get("orchestration", {})
    if orchestration:
        table.add_row("Workers", str(orchestration.get("workers", 0)))
        table.add_row("Verifications", str(orchestration.get("verifications", 0)))
        confidence = orchestration.get("routing_confidence")
        if confidence is not None:
            table.add_row("Routing Confidence", f"{confidence:.0%}" if isinstance(confidence, float) else str(confidence))
    verification = task.get("automatic_verification", {})
    if verification:
        table.add_row(
            "Auto Checks",
            (
                f"{verification.get('total', 0)} total "
                f"(compile {verification.get('compile', 0)} / "
                f"lint {verification.get('lint', 0)} / test {verification.get('test', 0)})"
            ),
        )

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


def _format_tokens(token_usage: dict, *, detailed: bool = False) -> str:
    """Format token usage for task status output."""
    if not token_usage:
        return "-"
    input_tokens = int(token_usage.get("input", token_usage.get("input_tokens", 0)) or 0)
    output_tokens = int(token_usage.get("output", token_usage.get("output_tokens", 0)) or 0)
    orchestration_tokens = int(
        token_usage.get("orchestration", token_usage.get("orchestration_tokens", 0)) or 0
    )
    total = int(token_usage.get("total", 0) or 0) or input_tokens + output_tokens + orchestration_tokens
    if detailed:
        return (
            f"{total:,} total "
            f"(in {input_tokens:,} / out {output_tokens:,} / orch {orchestration_tokens:,})"
        )
    return f"{total:,}" if total else "-"
