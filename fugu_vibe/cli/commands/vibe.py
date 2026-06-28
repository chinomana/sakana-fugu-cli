"""
`fugu-vibe vibe` - Main interactive vibe coding session.

This is the primary command: opens an interactive session with
orchestration visualization, accepts text/voice input, and manages
tasks in real-time.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown

from fugu_vibe.api.client import FuguClient
from fugu_vibe.core.event_bus import EventBus, EventType
from fugu_vibe.core.orchestration import OrchestrationAnalyzer
from fugu_vibe.core.task_manager import TaskManager
from fugu_vibe.ui.dashboard import OrchestrationDashboard

if TYPE_CHECKING:
    from fugu_vibe.config import Config

console = Console()


@click.command()
@click.option("--model", "-m", help="Model to use")
@click.option("--effort", "-e", type=click.Choice(["high", "xhigh", "max"]), help="Reasoning effort")
@click.option("--web-search", "-w", is_flag=True, help="Enable web search")
@click.option(
    "--viz/--no-viz",
    default=False,
    help="Enable or disable orchestration visualization. Disabled by default for stable input.",
)
@click.option("--voice", "-v", is_flag=True, help="Enable voice input")
@click.option("--unlimited", "-u", is_flag=True, help="Unlimited prompt mode (no guardrails)")
@click.pass_context
def vibe_command(
    ctx: click.Context,
    model: str | None,
    effort: str | None,
    web_search: bool,
    viz: bool,
    voice: bool,
    unlimited: bool,
) -> None:
    """
    🚀 Start interactive vibe coding session.
    
    This is the main command - opens a full-screen dashboard with
    real-time orchestration visualization, and accepts text/voice input.
    
    Examples:
        fugu-vibe vibe                          # Default session
        fugu-vibe vibe --model fugu-ultra       # Use Fugu Ultra
        fugu-vibe vibe --effort xhigh           # Maximum reasoning
        fugu-vibe vibe --web-search             # Enable web search
        fugu-vibe vibe --viz                    # Enable dashboard visualization
        fugu-vibe vibe --voice                  # Enable voice control
        fugu-vibe vibe --unlimited              # No prompt restrictions
    """
    config: Config = ctx.obj["config"]
    
    # Override with CLI options
    if model:
        config.model.default = model
    if effort:
        config.model.reasoning_effort = effort  # type: ignore
    if unlimited:
        config.prompt.unlimited_mode = True
    
    # Run async session
    asyncio.run(_vibe_session(config, web_search, viz, voice))


async def _vibe_session(
    config: Config,
    web_search: bool,
    viz_enabled: bool,
    voice_enabled: bool,
) -> None:
    """Main vibe session loop."""
    
    # Initialize components
    event_bus = EventBus()
    await event_bus.start()
    
    fugu_client = FuguClient(config)
    task_manager = TaskManager(config, fugu_client, event_bus)
    await task_manager.start()
    
    # Start dashboard
    dashboard = None
    if viz_enabled:
        dashboard = OrchestrationDashboard(config, event_bus)
        await dashboard.start()
    
    # Start voice if requested
    voice_pipeline = None
    if voice_enabled:
        from fugu_vibe.voice.pipeline import VoicePipeline
        voice_pipeline = VoicePipeline(config, task_manager, event_bus)
        try:
            await voice_pipeline.start()
            console.print("[green]🎤 Voice input enabled (press Space to talk)[/green]")
        except RuntimeError as e:
            console.print(f"[yellow]Voice unavailable: {e}[/yellow]")
    
    # Prompt session for keyboard input
    session = PromptSession(
        message="> ",
        multiline=False,
        enable_suspend=True,
    )
    
    console.print("\n[bold cyan]🐡 Fugu Vibe Session Started[/bold cyan]")
    console.print("Type your prompt and press Enter")
    console.print("Commands: /status /tasks /quit /help  |  Exit: Ctrl+C or Ctrl+D\n")
    
    try:
        while True:
            try:
                # Get user input
                user_input = await session.prompt_async()
                user_input = user_input.strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.startswith("/"):
                    await _handle_command(
                        user_input, task_manager, event_bus, dashboard
                    )
                    continue
                
                # Send to Fugu
                await _send_to_fugu(
                    user_input, fugu_client, event_bus, config, web_search
                )
                
            except KeyboardInterrupt:
                break
            except EOFError:
                break
                
    finally:
        # Cleanup
        if voice_pipeline:
            await voice_pipeline.stop()
        if dashboard:
            await dashboard.stop()
        await task_manager.close()
        await event_bus.close()
        await fugu_client.close()
        
        console.print("\n[dim]Session ended.[/dim]")


async def _send_to_fugu(
    prompt: str,
    client: FuguClient,
    event_bus: EventBus,
    config: Config,
    web_search: bool,
) -> None:
    """Send a prompt to Fugu and stream the response."""
    
    messages = [{"role": "user", "content": prompt}]
    
    # Initialize orchestration analyzer
    analyzer = OrchestrationAnalyzer(config, event_bus)
    
    console.print(f"\n[dim]> {prompt[:80]}{'...' if len(prompt) > 80 else ''}[/dim]")
    console.print("[dim]Thinking...[/dim]", end="")
    
    try:
        async for chunk in client.send(
            messages=messages,
            model=config.model.default,
            effort=config.model.reasoning_effort,  # type: ignore
            web_search=web_search,
        ):
            # Analyze chunk for orchestration patterns
            event = await analyzer.analyze_chunk(chunk)
            
            if chunk.type == "content":
                console.print(chunk.content, end="")
            elif chunk.type == "token_usage":
                orch = chunk.token_usage.orchestration_tokens
                if orch > 0:
                    console.print(f"\n[dim](orch: {orch} tokens)[/dim]")
                    
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
    finally:
        await analyzer.finalize()
        console.print("\n")


async def _handle_command(
    cmd: str,
    task_manager: TaskManager,
    event_bus: EventBus,
    dashboard: OrchestrationDashboard | None,
) -> None:
    """Handle slash commands."""
    parts = cmd.split()
    command = parts[0].lower()
    
    if command in ("/quit", "/q", "/exit"):
        raise EOFError()
        
    elif command == "/status":
        status = await task_manager.status()
        console.print(f"\nRunning: {status['running']}, Queued: {status['queued']}")
        
    elif command == "/tasks":
        status = await task_manager.status()
        for task in status["tasks"]:
            icon = "🔄" if task['status'] == 'running' else "✅" if task['status'] == 'completed' else "⏳"
            console.print(f"  {icon} {task['name']} [{task['status']}]")
            
    elif command == "/help":
        console.print("\n[bold]Commands:[/bold]")
        console.print("  /quit, /q     - Exit session")
        console.print("  /status       - Show system status")
        console.print("  /tasks        - List active tasks")
        console.print("  /help         - Show this help")
        console.print("")
