"""
`fugu-vibe submit` - Submit async tasks with DAG dependency support.
"""

from __future__ import annotations

import asyncio
import contextlib

import click
from rich.console import Console
from rich.markdown import Markdown

from fugu_vibe.api.client import FuguClient
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.task_manager import TaskManager

console = Console()


@click.command()
@click.argument("name")
@click.option("--prompt", "-p", required=True, help="Task prompt/instruction")
@click.option("--description", "-d", default="", help="Task description")
@click.option("--model", "-m", help="Model to use")
@click.option("--effort", "-e", type=click.Choice(["high", "xhigh", "max"]), help="Reasoning effort")
@click.option("--web-search", "-w", is_flag=True, help="Enable web search")
@click.option("--depends-on", multiple=True, help="Task IDs this task depends on")
@click.option(
    "--files",
    "-f",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Files to include in context",
)
@click.option("--wait", is_flag=True, help="Wait for task to complete")
@click.option("--unlimited", "-u", is_flag=True, help="Unlimited prompt mode")
@click.pass_context
def submit_command(
    ctx: click.Context,
    name: str,
    prompt: str,
    description: str,
    model: str | None,
    effort: str | None,
    web_search: bool,
    depends_on: tuple[str, ...],
    files: tuple[str, ...],
    wait: bool,
    unlimited: bool,
) -> None:
    """
    📤 Submit a task for async execution.

    Tasks run in isolated git worktrees and can have dependencies
    forming a DAG (Directed Acyclic Graph).

    Examples:
        fugu-vibe submit "Refactor auth" -p "Refactor the auth module..."
        fugu-vibe submit "Write tests" -p "..." --depends-on <task-id>
        fugu-vibe submit "Search docs" -p "..." --web-search
        fugu-vibe submit "Deep analysis" -p "..." --effort xhigh --wait
    """
    config = ctx.obj["config"]

    if unlimited:
        config.prompt.unlimited_mode = True

    asyncio.run(_submit(
        config, name, prompt, description, model, effort,
        web_search, list(depends_on), list(files), wait,
    ))


async def _submit(
    config, name, prompt, description, model, effort,
    web_search, depends_on, files, wait,
) -> None:
    event_bus = EventBus()
    await event_bus.start()

    client = FuguClient(config)
    task_manager = TaskManager(config, client, event_bus)
    await task_manager.start()

    try:
        task = await task_manager.submit(
            name=name,
            prompt=prompt,
            description=description,
            model=model or config.model.default,
            effort=effort or config.model.reasoning_effort,
            web_search=web_search,
            depends_on=depends_on,
            files=files,
        )

        console.print(f"[green]✅ Task submitted:[/green] {task.task_id}")
        console.print(f"   Name: {task.name}")
        console.print(f"   Status: {task.status.value}")
        if task.depends_on:
            console.print(f"   Depends on: {', '.join(task.depends_on)}")

        if wait:
            console.print("[dim]Waiting for completion...[/dim]")
            await _wait_for_task(task)

            if task.status.value in ("completed", "merged"):
                console.print(f"\n[green]✅ {task.status.value.title()}[/green] ({task.duration:.1f}s)")
                if task.output:
                    console.print(Markdown(task.output))
            else:
                console.print(f"\n[red]❌ Failed:[/red] {task.error}")
        else:
            console.print(f"\nRun `fugu-vibe status {task.task_id}` from another terminal to check progress")

    finally:
        if not wait:
            # Keep this process alive; there is no daemon yet.
            console.print("[dim]Task running in this process. Press Ctrl+C to stop it.[/dim]")
            await _wait_until_cancelled()

        await task_manager.close()
        await event_bus.close()
        await client.close()


async def _wait_for_task(task) -> None:
    stop = asyncio.Event()
    while not task.is_terminal:
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            continue


async def _wait_until_cancelled() -> None:
    stop = asyncio.Event()
    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        await stop.wait()
