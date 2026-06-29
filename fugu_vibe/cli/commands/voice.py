"""
`fugu-vibe voice` - Voice-controlled task submission.
"""

from __future__ import annotations

import asyncio
import contextlib

import click
from rich.console import Console

from fugu_vibe.api.client import FuguClient
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.task_manager import TaskManager

console = Console()


@click.command()
@click.option("--model", "-m", help="Model to use")
@click.option("--effort", "-e", type=click.Choice(["high", "xhigh", "max"]), help="Reasoning effort")
@click.option("--web-search", "-w", is_flag=True, help="Enable web search")
@click.option("--continuous", "-c", is_flag=True, help="Continuous voice mode")
@click.pass_context
def voice_command(ctx: click.Context, model: str | None, effort: str | None,
                  web_search: bool, continuous: bool) -> None:
    """
    🎤 Submit tasks using voice input.

    Press Space (or configured key) to start recording,
    speak your instruction, then release to submit.

    Requires: pip install fugu-vibe-cli[voice]

    Examples:
        fugu-vibe voice                    # Single voice command
        fugu-vibe voice -c                 # Continuous voice mode
        fugu-vibe voice --web-search       # Enable web search
    """
    config = ctx.obj["config"]

    if model:
        config.model.default = model
    if effort:
        config.model.reasoning_effort = effort  # type: ignore

    asyncio.run(_voice_mode(config, web_search, continuous))


async def _voice_mode(config, web_search: bool, continuous: bool) -> None:
    from fugu_vibe.voice.pipeline import VoicePipeline

    event_bus = EventBus()
    await event_bus.start()

    client = FuguClient(config)
    task_manager = TaskManager(config, client, event_bus)
    await task_manager.start()

    pipeline = VoicePipeline(config, task_manager, event_bus)

    try:
        await pipeline.start()

        if continuous:
            console.print("[bold green]🎤 Continuous voice mode[/bold green]")
            console.print("Press Space to speak, Ctrl+C to exit\n")

            await _wait_for_keyboard_interrupt()
        else:
            console.print("[bold]🎤 Press Space to speak...[/bold]")
            # Single recording
            await pipeline.record_and_submit()

    except RuntimeError as e:
        console.print(f"[red]Voice error: {e}[/red]")
        console.print("[dim]Install voice support: pip install fugu-vibe-cli[voice][/dim]")
    finally:
        await pipeline.stop()
        await task_manager.close()
        await event_bus.close()
        await client.close()


async def _wait_for_keyboard_interrupt() -> None:
    stop = asyncio.Event()
    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        await stop.wait()
