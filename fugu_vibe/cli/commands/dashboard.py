"""`fugu-vibe dashboard` - View workspace events in a separate terminal."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console

from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.event_log import event_log_path, parse_event_line
from fugu_vibe.ui.dashboard import OrchestrationDashboard

if TYPE_CHECKING:
    from fugu_vibe.config import Config

console = Console()


@click.command(name="dashboard")
@click.option(
    "--event-log",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the workspace event log. Defaults to .fugu-vibe/events.jsonl",
)
@click.option("--poll-interval", default=0.25, show_default=True, help="Polling interval in seconds")
@click.pass_context
def dashboard_command(
    ctx: click.Context,
    event_log: Path | None,
    poll_interval: float,
) -> None:
    """📊 Open a dashboard for a running workspace vibe session."""
    config: Config = ctx.obj["config"]
    asyncio.run(_dashboard_session(config, event_log, poll_interval))


async def _dashboard_session(
    config: Config,
    path: Path | None,
    poll_interval: float,
) -> None:
    log_path = event_log_path(path)
    console.print(f"[dim]Watching event log: {log_path}[/dim]")
    if not log_path.exists():
        console.print("[yellow]Waiting for a vibe session to create events...[/yellow]")
    event_bus = EventBus()
    await event_bus.start()
    dashboard = OrchestrationDashboard(config, event_bus)

    try:
        await dashboard.start()
        await _follow_event_log(event_bus, log_path, poll_interval)
    finally:
        await dashboard.stop()
        await event_bus.close()
        console.print("\n[dim]Dashboard ended.[/dim]")


async def _follow_event_log(event_bus: EventBus, path: Path, poll_interval: float) -> None:
    """Tail the JSONL event log and replay events into the local dashboard."""
    position = 0

    while True:
        try:
            exists = await asyncio.to_thread(path.exists)
            if not exists:
                await asyncio.sleep(poll_interval)
                continue

            with path.open("r", encoding="utf-8") as f:
                f.seek(position)
                for line in f:
                    parsed = parse_event_line(line)
                    if parsed:
                        event_type, data, source = parsed
                        await event_bus.emit(event_type, data, source=source)
                position = f.tell()

            await asyncio.sleep(poll_interval)
        except KeyboardInterrupt:
            break
        except asyncio.CancelledError:
            break
