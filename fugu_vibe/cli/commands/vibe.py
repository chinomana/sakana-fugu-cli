"""
`fugu-vibe vibe` - Main interactive vibe coding session.

This is the primary command: opens an interactive session with
orchestration visualization, accepts text/voice input, and manages
tasks in real-time.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

import click
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from fugu_vibe.api.client import FuguClient
from fugu_vibe.agent import AgentLoop, ToolRegistry
from fugu_vibe.context import ContextManager
from fugu_vibe.core.attachments import build_content_parts
from fugu_vibe.core.event_bus import EventBus, EventType
from fugu_vibe.core.event_log import EventLogWriter
from fugu_vibe.core.orchestration import OrchestrationAnalyzer
from fugu_vibe.core.patch_capture import capture_unified_diff
from fugu_vibe.core.session_output import SessionOutputWriter
from fugu_vibe.core.task_manager import TaskManager
from fugu_vibe.tools import FileToolError, FileTools, PatchTool, PatchToolError, TerminalTool, TerminalToolError
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
@click.option(
    "--file",
    "-f",
    "files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Attach a PDF, image, or file to each prompt. Can be used multiple times.",
)
@click.option("--unlimited", "-u", is_flag=True, help="Unlimited prompt mode (no guardrails)")
@click.pass_context
def vibe_command(
    ctx: click.Context,
    model: str | None,
    effort: str | None,
    web_search: bool,
    viz: bool,
    voice: bool,
    files: tuple[Path, ...],
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
        fugu-vibe vibe -f spec.pdf -f photo.png # Attach files
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
    asyncio.run(_vibe_session(config, web_search, viz, voice, list(files)))


async def _vibe_session(
    config: Config,
    web_search: bool,
    viz_enabled: bool,
    voice_enabled: bool,
    initial_files: list[Path],
) -> None:
    """Main vibe session loop."""
    
    # Initialize components
    event_bus = EventBus()
    event_log = EventLogWriter(event_bus)
    event_log.start()
    await event_bus.start()
    
    fugu_client = FuguClient(config)
    task_manager = TaskManager(config, fugu_client, event_bus)
    await task_manager.start()
    
    # Start dashboard
    dashboard = None
    if viz_enabled:
        console.print(
            "[yellow]Inline dashboard is disabled to keep keyboard input stable.[/yellow] "
            "[dim]Run `fugu-vibe dashboard` in a second terminal instead.[/dim]"
        )
    
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
    output_writer = SessionOutputWriter()
    context = ContextManager()
    file_tools = FileTools(Path.cwd())
    patch_tool = PatchTool(Path.cwd())
    tool_registry = ToolRegistry(file_tools)
    terminal_tool = TerminalTool(
        Path.cwd(),
        enabled=config.tools.terminal_enabled,
        approval=config.tools.terminal_approval,
        timeout_seconds=config.tools.terminal_timeout_seconds,
        max_output_chars=config.tools.max_output_chars,
    )
    for path in initial_files:
        context.add_attachment(path)
    
    console.print("\n[bold cyan]🐡 Fugu Vibe Session Started[/bold cyan]")
    console.print("Type your prompt and press Enter")
    console.print("Commands: /context /compact /ls /read /search /diff /apply /tools /terminal /quit /help")
    console.print("Exit: Ctrl+C or Ctrl+D\n")
    console.print(f"[dim]Session output: {output_writer.path}[/dim]")
    if context.attachments:
        console.print(f"[dim]Attached {len(context.attachments)} file(s). Use /files to list them.[/dim]\n")
    
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
                        user_input,
                        task_manager,
                        event_bus,
                        dashboard,
                        context,
                        file_tools,
                        patch_tool,
                        config.patch.mode,
                        terminal_tool,
                        session,
                    )
                    continue
                
                # Send to Fugu
                await _send_to_fugu(
                    user_input,
                    fugu_client,
                    event_bus,
                    config,
                    web_search,
                    context,
                    output_writer,
                    tool_registry,
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
    context: ContextManager,
    output_writer: SessionOutputWriter,
    tool_registry: ToolRegistry,
) -> None:
    """Send a prompt to Fugu and stream the response."""

    files = context.attachments
    content = build_content_parts(prompt, files) if files else prompt
    user_message = {"role": "user", "content": content}
    messages = context.messages_for(user_message)
    
    # Initialize orchestration analyzer
    analyzer = OrchestrationAnalyzer(config, event_bus)
    
    console.print(f"\n[dim]> {prompt[:80]}{'...' if len(prompt) > 80 else ''}[/dim]")
    if files:
        names = ", ".join(path.name for path in files)
        console.print(f"[dim]Attachments: {names}[/dim]")
    console.print("[dim]Thinking...[/dim]", end="")
    output_writer.start_turn(prompt, files)
    response_parts: list[str] = []
    
    try:
        def on_content(content_piece: str):
            if content_piece:
                response_parts.append(content_piece)
                output_writer.append_response(content_piece)
                console.print(content_piece, end="")

        def on_tool_call(tool_call: dict):
            name = tool_call.get("name", "unknown")
            console.print(f"\n[dim]Tool call: {name}[/dim]")

        agent_loop = AgentLoop(client, tool_registry, event_bus)
        result = await agent_loop.run(
            messages=messages,
            model=config.model.default,
            effort=config.model.reasoning_effort,  # type: ignore
            web_search=web_search,
            on_content=on_content,
            on_tool_call=on_tool_call,
        )
        if result.tool_calls:
            context.record_tool_usage("agent.tools", {"count": len(result.tool_calls)}, len(result.tool_calls))
                    
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
    finally:
        response = "".join(response_parts)
        if response:
            captured_patch = capture_unified_diff(response)
            if captured_patch:
                try:
                    PatchTool(Path.cwd()).check(captured_patch.latest_path.read_text(encoding="utf-8"))
                    console.print(
                        f"\n[green]Saved proposed patch:[/green] {captured_patch.latest_path}\n"
                        f"[dim]Review/apply with: /apply {captured_patch.latest_path}[/dim]"
                    )
                except PatchToolError as e:
                    console.print(
                        f"\n[yellow]Saved proposed patch, but git apply --check failed:[/yellow] {captured_patch.latest_path}\n"
                        f"[red]{e}[/red]"
                    )
            context.add_turn(user_message, response)
        await analyzer.finalize()
        output_writer.end_turn()
        console.print("\n")


async def _handle_command(
    cmd: str,
    task_manager: TaskManager,
    event_bus: EventBus,
    dashboard: OrchestrationDashboard | None,
    context: ContextManager,
    file_tools: FileTools,
    patch_tool: PatchTool,
    patch_mode: str,
    terminal_tool: TerminalTool,
    session: PromptSession,
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

    elif command == "/attach":
        for raw_path in _command_args(cmd):
            try:
                path = context.add_attachment(Path(raw_path))
            except FileNotFoundError:
                console.print(f"[red]Not a file:[/red] {raw_path}")
                continue
            console.print(f"[green]Attached:[/green] {path}")

    elif command == "/files":
        if not context.attachments:
            console.print("[dim]No files attached.[/dim]")
        for index, path in enumerate(context.attachments, start=1):
            console.print(f"  {index}. {path}")

    elif command == "/clear-files":
        context.clear_attachments()
        console.print("[green]Cleared attached files.[/green]")

    elif command == "/context":
        _print_context(context)

    elif command == "/compact":
        console.print(f"[green]{context.compact()}[/green]")

    elif command == "/ls":
        args = _command_args(cmd)
        pattern = args[0] if args else "**/*"
        count = _print_file_list(file_tools, pattern)
        context.record_tool_usage("file.list", {"pattern": pattern}, count)

    elif command == "/read":
        args = _command_args(cmd)
        if not args:
            console.print("[red]Usage:[/red] /read PATH")
        else:
            count = _print_file_content(file_tools, args[0])
            context.record_tool_usage("file.read", {"path": args[0]}, count)

    elif command == "/search":
        args = _command_args(cmd)
        if not args:
            console.print("[red]Usage:[/red] /search QUERY [GLOB]")
        else:
            query = args[0]
            pattern = args[1] if len(args) > 1 else "**/*"
            count = _print_search_results(file_tools, query, pattern)
            context.record_tool_usage("file.search", {"query": query, "pattern": pattern}, count)

    elif command == "/tools":
        _print_tools_status(terminal_tool)

    elif command == "/diff":
        count = _print_git_diff(patch_tool)
        context.record_tool_usage("git.diff", {}, count)

    elif command == "/apply":
        args = _command_args(cmd)
        if not args:
            console.print("[red]Usage:[/red] /apply PATCH_FILE")
        else:
            count = await _apply_patch_file(patch_tool, args[0], patch_mode, session)
            context.record_tool_usage("patch.apply", {"path": args[0], "mode": patch_mode}, count)

    elif command == "/terminal":
        command_text = cmd[len("/terminal"):].strip()
        if not command_text:
            console.print("[red]Usage:[/red] /terminal COMMAND")
        else:
            result_count = await _run_terminal_command(terminal_tool, command_text)
            context.record_tool_usage("terminal.run", {"command": command_text}, result_count)
            
    elif command == "/help":
        console.print("\n[bold]Commands:[/bold]")
        console.print("  /quit, /q     - Exit session")
        console.print("  /context      - Show current prompt context")
        console.print("  /compact      - Compact older conversation turns")
        console.print("  /ls [GLOB]    - List workspace files")
        console.print("  /read PATH    - Read a workspace text file")
        console.print("  /search Q [G] - Search workspace text files")
        console.print("  /diff         - Show current git diff")
        console.print("  /apply FILE   - Check and apply a unified diff")
        console.print("  /tools        - Show local tool policy")
        console.print("  /terminal CMD - Run a terminal command if enabled")
        console.print("  /attach PATH  - Attach a PDF, image, or file")
        console.print("  /files        - List attached files")
        console.print("  /clear-files  - Remove all attached files")
        console.print("  /status       - Show system status")
        console.print("  /tasks        - List active tasks")
        console.print("  /help         - Show this help")
        console.print("")


def _command_args(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd)[1:]
    except ValueError as e:
        console.print(f"[red]Invalid command syntax:[/red] {e}")
        return []


def _print_context(context: ContextManager) -> None:
    summary = context.summary()
    console.print("\n[bold]Context[/bold]")
    console.print(f"  Turns: {summary.turns}")
    console.print(f"  History messages: {summary.history_messages}")
    console.print(f"  Compacted: {'yes' if summary.compacted else 'no'}")
    if summary.compacted:
        console.print(f"  Compact summary chars: {summary.compact_summary_chars}")
    console.print(f"  Metadata: {summary.metadata_path}")

    if summary.attachments:
        table = Table(show_header=True)
        table.add_column("#")
        table.add_column("File")
        table.add_column("Size")
        for index, attachment in enumerate(summary.attachments, start=1):
            size = attachment.get("size_bytes")
            table.add_row(str(index), str(attachment.get("path", "")), _format_size(size))
        console.print(table)
    else:
        console.print("  Attachments: none")


def _format_size(size: int | None) -> str:
    if size is None:
        return "unknown"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _print_file_list(file_tools: FileTools, pattern: str) -> int:
    try:
        files = file_tools.list_files(pattern)
    except FileToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0
    if not files:
        console.print("[dim]No files matched.[/dim]")
        return 0
    for path in files:
        console.print(path)
    return len(files)


def _print_file_content(file_tools: FileTools, path: str) -> int:
    try:
        content = file_tools.read_file(path)
    except FileToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0
    console.print(f"\n[bold]{path}[/bold]")
    lexer = Path(path).suffix.lstrip(".") or "text"
    console.print(Syntax(content, lexer, word_wrap=True))
    return 1


def _print_search_results(file_tools: FileTools, query: str, pattern: str) -> int:
    try:
        matches = file_tools.search(query, pattern)
    except FileToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0
    if not matches:
        console.print("[dim]No matches.[/dim]")
        return 0
    for match in matches:
        console.print(f"{match['path']}:{match['line']}: {match['text']}")
    return len(matches)


def _print_tools_status(terminal_tool: TerminalTool) -> None:
    status = terminal_tool.status()
    table = Table(show_header=True)
    table.add_column("Tool")
    table.add_column("Enabled")
    table.add_column("Policy")
    table.add_row(
        "terminal.run",
        "yes" if status["terminal_enabled"] else "no",
        str(status["terminal_approval"]),
    )
    console.print(table)
    console.print(f"[dim]Timeout: {status['timeout_seconds']}s, max output: {status['max_output_chars']} chars[/dim]")


async def _run_terminal_command(terminal_tool: TerminalTool, command: str) -> int:
    try:
        result = await terminal_tool.run(command)
    except TerminalToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0

    status = "timed out" if result.timed_out else f"exit {result.exit_code}"
    console.print(f"[dim]terminal.run {result.run_id}: {status} in {result.duration_seconds:.2f}s[/dim]")
    if result.stdout:
        console.print("[bold]stdout[/bold]")
        console.print(result.stdout)
    if result.stderr:
        console.print("[bold]stderr[/bold]")
        console.print(result.stderr)
    console.print(f"[dim]Log: {result.log_path}[/dim]")
    return 1


def _print_git_diff(patch_tool: PatchTool) -> int:
    try:
        diff = patch_tool.git_diff()
    except PatchToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0
    if not diff:
        console.print("[dim]No git diff.[/dim]")
        return 0
    console.print(Syntax(diff, "diff", word_wrap=True))
    return 1


async def _apply_patch_file(
    patch_tool: PatchTool,
    path: str,
    patch_mode: str,
    session: PromptSession,
) -> int:
    try:
        patch_text = patch_tool.read_patch_file(path)
        patch_tool.check(patch_text)
    except PatchToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0

    console.print(Syntax(patch_text, "diff", word_wrap=True))
    if patch_mode == "propose-only":
        console.print("[yellow]Patch policy is propose-only; not applying.[/yellow]")
        return 0

    if patch_mode == "ask-apply":
        answer = await session.prompt_async("Apply this patch? Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            console.print("[yellow]Patch skipped.[/yellow]")
            return 0

    try:
        patch_tool.apply(patch_text)
    except PatchToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0
    console.print("[green]Patch applied.[/green]")
    return 1
