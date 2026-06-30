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
from typing import TYPE_CHECKING, Any

import click
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from fugu_vibe.agent import AgentLoop, ToolRegistry
from fugu_vibe.api.client import FuguClient
from fugu_vibe.context import ContextManager
from fugu_vibe.core.attachments import build_content_parts
from fugu_vibe.core.checkpoints import CheckpointError, CheckpointManager
from fugu_vibe.core.effort import select_effort
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.event_log import EventLogWriter
from fugu_vibe.core.instructions import build_instructions
from fugu_vibe.core.orchestration import OrchestrationAnalyzer
from fugu_vibe.core.patch_capture import capture_unified_diff
from fugu_vibe.core.session_output import SessionOutputWriter
from fugu_vibe.core.task_manager import TaskManager
from fugu_vibe.mcp import MCPConfigStore, MCPToolManager
from fugu_vibe.tools import (
    FileToolError,
    FileTools,
    GitTools,
    PatchTool,
    PatchToolError,
    TerminalTool,
    TerminalToolError,
)
from fugu_vibe.ui.dashboard import OrchestrationDashboard

if TYPE_CHECKING:
    from fugu_vibe.config import Config

console = Console()

CODING_AGENT_INSTRUCTIONS = """You are operating inside fugu-vibe as a controlled coding agent.
Use structured tools to inspect, modify, run, and verify workspace changes. Available automatic tools include file_list, file_glob, file_read, file_search, file_grep, file_edit, file_delete, file_mkdir, file_write, bash, run_test, run_lint, git_status, git_diff, git_log, and git_show.
Tool-use rules:
- If the user asks you to inspect files, call file_read/file_search/file_grep instead of guessing.
- If the user asks you to modify code, call file_edit or file_write. Do not print a patch or diff as the primary way to make changes.
- Prefer file_edit for local edits instead of full-file rewrites. Keep all writes inside the selected workspace.
- After changing files, verify with run_test/run_lint/bash as appropriate. Automatic compile/test checks may also run; use their results to fix mistakes before finalizing.
- If verification fails, inspect the error, edit again, and re-run verification instead of declaring success.
- Final answers should summarize changed files and verification results. Do not include full diffs unless explicitly requested.
Only produce a git apply compatible unified diff if tool calls are unavailable or direct writes fail.
Avoid repeatedly calling the same tool with the same arguments.
"""


@click.command()
@click.option("--model", "-m", help="Model to use")
@click.option(
    "--effort", "-e", type=click.Choice(["high", "xhigh", "max"]), help="Reasoning effort"
)
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
@click.option(
    "--resume",
    "resume_session",
    default=None,
    help="Resume a persisted session id. Use 'latest' to resume the most recent session.",
)
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
    resume_session: str | None,
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
    config_path: Path | None = ctx.obj.get("config_path")
    workspace: Path = ctx.obj.get("workspace", Path.cwd())

    # Override with CLI options
    if model:
        config.model.default = model
    if effort:
        config.model.reasoning_effort = effort  # type: ignore
    if unlimited:
        config.prompt.unlimited_mode = True

    # Run async session
    asyncio.run(
        _vibe_session(
            config, web_search, viz, voice, list(files), workspace, config_path, resume_session
        )
    )


async def _vibe_session(
    config: Config,
    web_search: bool,
    viz_enabled: bool,
    voice_enabled: bool,
    initial_files: list[Path],
    workspace: Path,
    config_path: Path | None,
    resume_session: str | None,
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
    context = ContextManager(workspace, session_id=resume_session)
    output_writer = SessionOutputWriter(workspace)
    file_tools = FileTools(Path.cwd(), safety_mode=config.safety.mode)
    checkpoint_manager = CheckpointManager(Path.cwd())
    patch_tool = PatchTool(Path.cwd())
    terminal_tool = TerminalTool(
        Path.cwd(),
        enabled=config.tools.terminal_enabled,
        approval=config.tools.terminal_approval,
        safety_mode=config.safety.mode,
        timeout_seconds=config.tools.terminal_timeout_seconds,
        max_output_chars=config.tools.max_output_chars,
    )

    async def approve_tool_operation(name: str, args: dict[str, Any], preview: str) -> bool:
        console.print(f"\n[yellow]Approval required for {name}:[/yellow] {args.get('path', '')}")
        if preview:
            console.print(Syntax(preview, "diff", word_wrap=True))
        answer = await session.prompt_async("Approve this change? Type 'yes' to continue: ")
        return answer.strip().lower() == "yes"

    mcp_tools = None
    if config.mcp.enabled:
        mcp_tools = MCPToolManager(
            MCPConfigStore(workspace),
            timeout_seconds=config.mcp.timeout_seconds,
        )
    tool_registry = ToolRegistry(
        file_tools,
        terminal_tool=terminal_tool,
        git_tools=GitTools(Path.cwd(), max_output_chars=config.tools.max_output_chars),
        approval_callback=approve_tool_operation,
        mcp_tools=mcp_tools,
    )
    for path in initial_files:
        context.add_attachment(path)

    console.print("\n[bold cyan]🐡 Fugu Vibe Session Started[/bold cyan]")
    console.print(f"[dim]Workspace: {workspace}[/dim]")
    console.print(f"[dim]Config: {config_path or 'defaults only'}[/dim]")
    console.print(f"[dim]API base URL: {config.api.base_url}[/dim]")
    if config_path is None and config.api.base_url == "https://api.sakana.ai/v1":
        console.print(
            "[yellow]No .fugu-vibe.toml or user config was found; using the default Sakana API URL.[/yellow] "
            "[dim]Use -C, --config, --base-url, or FUGU_VIBE_API_BASE_URL to select your proxy.[/dim]"
        )
    if resume_session:
        console.print(f"[green]Resumed session:[/green] {context.session_store.session_id}")
        console.print(f"[dim]Loaded {len(context.history) // 2} prior turn(s).[/dim]")

    console.print("Type your prompt and press Enter")
    console.print(
        "Commands: /context /index /select /compact /ls /read /search /diff /apply /tools /terminal /quit /help"
    )
    console.print("Exit: Ctrl+C or Ctrl+D\n")
    console.print(f"[dim]Session output: {output_writer.path}[/dim]")
    if context.attachments:
        console.print(
            f"[dim]Attached {len(context.attachments)} file(s). Use /files to list them.[/dim]\n"
        )

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
                        checkpoint_manager,
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
                    checkpoint_manager,
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
    checkpoint_manager: CheckpointManager,
) -> None:
    """Send a prompt to Fugu and stream the response."""

    files = context.attachments
    content = build_content_parts(prompt, files) if files else prompt
    user_message = {"role": "user", "content": content}
    messages = context.messages_for(user_message)

    # Initialize orchestration analyzer
    analyzer = OrchestrationAnalyzer(config, event_bus)
    effort_decision = select_effort(
        prompt,
        config.model.reasoning_effort,  # type: ignore[arg-type]
        adaptive=config.model.adaptive_effort,
        attachment_count=len(files),
    )
    instructions = (
        build_instructions(CODING_AGENT_INSTRUCTIONS, Path.cwd())
        if config.prompt.use_instruction_templates
        else CODING_AGENT_INSTRUCTIONS
    )

    console.print(f"\n[dim]> {prompt[:80]}{'...' if len(prompt) > 80 else ''}[/dim]")
    if files:
        names = ", ".join(path.name for path in files)
        console.print(f"[dim]Attachments: {names}[/dim]")
    console.print(f"[dim]Effort: {effort_decision.effort} ({effort_decision.reason})[/dim]")
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

        agent_loop = AgentLoop(
            client,
            tool_registry,
            event_bus,
            max_tool_rounds=config.tools.max_tool_rounds,
            auto_test_after_edit=config.tools.auto_test_after_edit,
            auto_test_command=config.tools.auto_test_command,
            auto_compile_after_edit=config.tools.auto_compile_after_edit,
            auto_lint_after_edit=config.tools.auto_lint_after_edit,
            auto_lint_command=config.tools.auto_lint_command,
        )
        result = await agent_loop.run(
            messages=messages,
            model=config.model.default,
            effort=effort_decision.effort,
            web_search=web_search,
            instructions=instructions,
            max_output_tokens=min(config.model.max_output_tokens, 4096),
            on_content=on_content,
            on_tool_call=on_tool_call,
            on_chunk=analyzer.analyze_chunk,
        )
        if result.tool_calls:
            context.record_tool_usage(
                "agent.tools", {"count": len(result.tool_calls)}, len(result.tool_calls)
            )
            _maybe_create_turn_checkpoint(config, checkpoint_manager, result.tool_calls)
        if result.content and not response_parts:
            on_content(result.content)
        tool_calls = result.tool_calls

    except Exception as e:
        tool_calls = []
        console.print(f"\n[red]Error: {e}[/red]")
    finally:
        response = "".join(response_parts)
        if response:
            captured_patch = capture_unified_diff(response)
            if captured_patch:
                try:
                    PatchTool(Path.cwd()).check(
                        captured_patch.latest_path.read_text(encoding="utf-8")
                    )
                    if not tool_calls:
                        console.print(
                            "\n[yellow]The model produced a patch instead of using file tools.[/yellow] "
                            "[dim]Use /apply to review it, or retry with: make the change using file_edit/file_write.[/dim]"
                        )
                    console.print(
                        f"\n[green]Saved proposed patch:[/green] {captured_patch.latest_path}\n"
                        f"[dim]Review/apply with: /apply {captured_patch.latest_path}[/dim]"
                    )
                except PatchToolError as e:
                    console.print(
                        f"\n[yellow]Saved proposed patch, but git apply --check failed:[/yellow] {captured_patch.latest_path}\n"
                        f"[red]{e}[/red]"
                    )
            context.add_turn(user_message, response, tool_calls=tool_calls)
        await analyzer.finalize()
        output_writer.end_turn()
        console.print("\n")


def _maybe_create_turn_checkpoint(
    config: Config,
    checkpoint_manager: CheckpointManager,
    tool_calls: list[dict[str, object]],
) -> None:
    if not config.safety.checkpoint_enabled or not config.safety.checkpoint_each_turn:
        return
    mutating_tools = {
        "file_write",
        "file_edit",
        "file_delete",
        "file_mkdir",
        "bash",
        "run_test",
        "run_lint",
    }
    used_tools = {str(call.get("name", "")).replace(".", "_") for call in tool_calls}
    if not mutating_tools.intersection(used_tools):
        return
    try:
        checkpoint = checkpoint_manager.create("auto-turn")
    except CheckpointError as e:
        console.print(f"[yellow]Checkpoint skipped:[/yellow] {e}")
        return
    console.print(f"[dim]Checkpoint saved: {checkpoint.id}[/dim]")


async def _handle_command(
    cmd: str,
    task_manager: TaskManager,
    event_bus: EventBus,
    dashboard: OrchestrationDashboard | None,
    context: ContextManager,
    file_tools: FileTools,
    checkpoint_manager: CheckpointManager,
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
            icon = (
                "🔄"
                if task["status"] == "running"
                else "✅"
                if task["status"] == "completed"
                else "⏳"
            )
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

    elif command == "/sessions":
        _print_sessions(context)

    elif command == "/index":
        data = context.rebuild_index()
        console.print(
            f"[green]Indexed {data['count']} file(s)[/green]"
            f"{' [yellow](truncated)[/yellow]' if data.get('truncated') else ''}"
        )

    elif command == "/select":
        query = cmd[len("/select") :].strip()
        if not query:
            console.print("[red]Usage:[/red] /select QUERY")
        else:
            _print_selected_context_files(context, query)

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

    elif command == "/checkpoint":
        message = cmd[len("/checkpoint") :].strip() or "manual checkpoint"
        _create_checkpoint(checkpoint_manager, message)

    elif command == "/checkpoints":
        _print_checkpoints(checkpoint_manager)

    elif command == "/undo":
        args = _command_args(cmd)
        _undo_checkpoint(checkpoint_manager, args[0] if args else None)

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
        command_text = cmd[len("/terminal") :].strip()
        if not command_text:
            console.print("[red]Usage:[/red] /terminal COMMAND")
        else:
            result_count = await _run_terminal_command(terminal_tool, command_text)
            context.record_tool_usage("terminal.run", {"command": command_text}, result_count)

    elif command == "/help":
        console.print("\n[bold]Commands:[/bold]")
        console.print("  /quit, /q     - Exit session")
        console.print("  /context      - Show current prompt context")
        console.print("  /sessions     - List persisted sessions")
        console.print("  /compact      - Compact older conversation turns")
        console.print("  /ls [GLOB]    - List workspace files")
        console.print("  /read PATH    - Read a workspace text file")
        console.print("  /search Q [G] - Search workspace text files")
        console.print("  /diff         - Show current git diff")
        console.print("  /apply FILE   - Check and apply a unified diff")
        console.print("  /tools        - Show local tool policy")
        console.print("  /checkpoint [MSG] - Save current git diff for rollback")
        console.print("  /checkpoints  - List saved checkpoints")
        console.print("  /undo [ID]    - Reverse the latest or selected checkpoint")
        console.print("  /terminal CMD - Run a terminal command if enabled")
        console.print("  /attach PATH  - Attach a PDF, image, or file")
        console.print("  /files        - List attached files")
        console.print("  /clear-files  - Remove all attached files")
        console.print("  /status       - Show system status")
        console.print("  /index        - Rebuild workspace codebase index")
        console.print("  /select QUERY - Show files likely relevant to a query")

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
    console.print(f"  Session: {summary.session_id}")
    console.print(f"  Session history: {summary.session_path}")
    console.print(f"  Index: {summary.indexed_files} file(s) at {summary.index_path}")
    if summary.index_truncated:
        console.print("  Index truncated: yes")

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


def _print_sessions(context: ContextManager) -> None:
    sessions = context.session_store.list_sessions(context.workspace)
    if not sessions:
        console.print("[dim]No persisted sessions.[/dim]")
        return
    table = Table(show_header=True)
    table.add_column("Session")
    table.add_column("Status")
    table.add_column("Turns")
    table.add_column("Files")
    table.add_column("Updated")
    for session_info in sessions:
        session_id = str(session_info.get("session_id", ""))
        if session_id == context.session_store.session_id:
            session_id = f"* {session_id}"
        table.add_row(
            session_id,
            str(session_info.get("status", "unknown")),
            str(session_info.get("turns", 0)),
            str(session_info.get("attachments", 0)),
            str(session_info.get("updated_at", "")),
        )
    console.print(table)


def _format_size(size: int | None) -> str:
    if size is None:
        return "unknown"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _print_selected_context_files(context: ContextManager, query: str) -> int:
    matches = context.select_context_files(query)
    if not matches:
        console.print("[dim]No indexed files matched.[/dim]")
        return 0
    table = Table(show_header=True)
    table.add_column("Score order")
    table.add_column("File")
    table.add_column("Language")
    table.add_column("Symbols")
    for index, entry in enumerate(matches, start=1):
        table.add_row(
            str(index),
            str(entry.get("path", "")),
            str(entry.get("language", "")),
            ", ".join(str(symbol) for symbol in entry.get("symbols", [])[:6]),
        )
    console.print(table)
    return len(matches)


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
        str(status.get("safety_mode", status["terminal_approval"])),
    )
    console.print(table)
    console.print(
        f"[dim]Timeout: {status['timeout_seconds']}s, max output: {status['max_output_chars']} chars[/dim]"
    )


async def _run_terminal_command(terminal_tool: TerminalTool, command: str) -> int:
    try:
        result = await terminal_tool.run(command)
    except TerminalToolError as e:
        console.print(f"[red]{e}[/red]")
        return 0

    status = "timed out" if result.timed_out else f"exit {result.exit_code}"
    console.print(
        f"[dim]terminal.run {result.run_id}: {status} in {result.duration_seconds:.2f}s[/dim]"
    )
    if result.stdout:
        console.print("[bold]stdout[/bold]")
        console.print(result.stdout)
    if result.stderr:
        console.print("[bold]stderr[/bold]")
        console.print(result.stderr)
    console.print(f"[dim]Log: {result.log_path}[/dim]")
    return 1


def _create_checkpoint(checkpoint_manager: CheckpointManager, message: str) -> int:
    try:
        checkpoint = checkpoint_manager.create(message)
    except CheckpointError as e:
        console.print(f"[yellow]{e}[/yellow]")
        return 0
    console.print(f"[green]Checkpoint saved:[/green] {checkpoint.id}")
    if checkpoint.changed_files:
        console.print("[dim]Files: " + ", ".join(checkpoint.changed_files) + "[/dim]")
    return 1


def _print_checkpoints(checkpoint_manager: CheckpointManager) -> int:
    checkpoints = checkpoint_manager.list()
    if not checkpoints:
        console.print("[dim]No checkpoints saved.[/dim]")
        return 0
    table = Table(show_header=True)
    table.add_column("ID")
    table.add_column("Message")
    table.add_column("Files")
    table.add_column("Created")
    for checkpoint in checkpoints:
        table.add_row(
            str(checkpoint.get("id", "")),
            str(checkpoint.get("message", "")),
            str(len(checkpoint.get("changed_files", []))),
            str(checkpoint.get("created_at", "")),
        )
    console.print(table)
    return len(checkpoints)


def _undo_checkpoint(
    checkpoint_manager: CheckpointManager, checkpoint_id: str | None = None
) -> int:
    try:
        result = checkpoint_manager.undo(checkpoint_id)
    except CheckpointError as e:
        console.print(f"[red]{e}[/red]")
        return 0
    console.print(f"[green]Undid checkpoint:[/green] {result['undone']}")
    changed_files = result.get("changed_files") or []
    if changed_files:
        console.print("[dim]Restored files: " + ", ".join(map(str, changed_files)) + "[/dim]")
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
