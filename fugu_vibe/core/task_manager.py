"""
Async task manager with git-worktree isolation and DAG dependencies.

Supports:
- Parallel task execution with configurable limits
- Task dependencies (DAG - Directed Acyclic Graph)
- Git worktree isolation per task
- Auto-merge on completion
- Background/foreground execution modes
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from git import Repo
from git.exc import GitCommandError

from fugu_vibe.core.attachments import build_content_parts
from fugu_vibe.core.event_bus import EventBus, EventType

TASK_AGENT_INSTRUCTIONS = """You are running as an unattended fugu-vibe task inside an isolated workspace.
Use structured workspace tools for code inspection and edits. Do not print patches when file_edit or file_write can apply the change directly. After edits, use compile/test/lint results to repair failures before finalizing with a concise summary.
"""

if TYPE_CHECKING:
    from fugu_vibe.api.client import FuguClient
    from fugu_vibe.config import Config

logger = structlog.get_logger()


class TaskStatus(Enum):
    """Task lifecycle states."""

    PENDING = "pending"           # Waiting for dependencies
    QUEUED = "queued"             # Ready but waiting for slot
    RUNNING = "running"           # Currently executing
    COMPLETED = "completed"       # Successfully finished
    FAILED = "failed"             # Error occurred
    CANCELLED = "cancelled"       # User cancelled
    MERGED = "merged"             # Changes merged to main


@dataclass
class Task:
    """A single Fugu task with metadata."""

    # Identity
    task_id: str
    name: str
    description: str = ""

    # Execution
    prompt: str = ""
    model: str = "fugu-ultra"
    effort: str = "xhigh"
    web_search: bool = False
    files: list[str] = field(default_factory=list)  # Files to include in context

    # Dependencies
    depends_on: list[str] = field(default_factory=list)  # task_ids

    # Git
    branch: str = ""
    worktree_path: str = ""

    # Status
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Results
    output: str = ""
    error: str = ""
    token_usage: dict = field(default_factory=dict)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        if self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.MERGED,
        )


class TaskManager:
    """
    Manages async Fugu tasks with git-worktree isolation.

    Usage:
        manager = TaskManager(config, fugu_client)
        await manager.start()

        # Submit tasks
        task1 = await manager.submit("Refactor auth", prompt="...")
        task2 = await manager.submit("Write tests", prompt="...", depends_on=[task1.task_id])

        # Monitor
        status = await manager.status()

        # Shutdown
        await manager.close()
    """

    def __init__(
        self,
        config: Config,
        fugu_client: FuguClient,
        event_bus: EventBus | None = None,
        *,
        run_scheduler: bool = True,
    ):
        self.config = config
        self.client = fugu_client
        self.event_bus = event_bus
        self.task_config = config.tasks

        # Task storage
        self._tasks: dict[str, Task] = {}
        self._dependency_graph: dict[str, set[str]] = defaultdict(set)
        self._reverse_deps: dict[str, set[str]] = defaultdict(set)

        # Concurrency control
        self._semaphore: asyncio.Semaphore | None = None
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._active_task_ids: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue()

        # Git
        self._repo: Repo | None = None
        self._repo_root: Path | None = None

        # State
        self._run_scheduler = run_scheduler
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._state_dir = Path.cwd() / ".fugu-vibe" / "tasks"

    async def start(self) -> None:
        """Initialize task manager and git repo."""
        self._semaphore = asyncio.Semaphore(self.task_config.max_parallel)
        self._running = True

        # Initialize git
        self._init_git()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._load_persisted_tasks()
        await self._recover_interrupted_tasks()

        # Start scheduler
        if self._run_scheduler:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

        logger.info(
            "task_manager_started",
            max_parallel=self.task_config.max_parallel,
            repo_root=str(self._repo_root) if self._repo_root else None,
        )

    async def close(self) -> None:
        """Shutdown task manager."""
        self._running = False

        # Cancel running tasks
        for task_id, task in self._running_tasks.items():
            task.cancel()
            self._tasks[task_id].status = TaskStatus.CANCELLED
            self._persist_task(self._tasks[task_id])

        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task

        logger.info("task_manager_stopped")

    def _init_git(self) -> None:
        """Initialize git repository for worktree management."""
        try:
            # Find git repo from current directory
            self._repo = Repo(search_parent_directories=True)
            self._repo_root = Path(self._repo.working_dir)
        except Exception:
            # No git repo - use temp directory
            self._repo_root = Path(tempfile.mkdtemp(prefix="fugu-vibe-"))
            self._repo = Repo.init(self._repo_root)
            logger.warning("no_git_repo_found", using_temp=str(self._repo_root))

    async def submit(
        self,
        name: str,
        prompt: str,
        description: str = "",
        model: str | None = None,
        effort: str = "xhigh",
        web_search: bool = False,
        files: list[str] | None = None,
        depends_on: list[str] | None = None,
        **metadata: Any,
    ) -> Task:
        """
        Submit a new task for execution.

        Args:
            name: Task name
            prompt: The prompt/instruction for Fugu
            description: Optional description
            model: Model to use (default from config)
            effort: Reasoning effort level
            web_search: Enable web search
            files: Files to include in context
            depends_on: Task IDs this task depends on
            **metadata: Additional metadata
        """
        task_id = self._generate_task_id(name)

        task = Task(
            task_id=task_id,
            name=name,
            description=description,
            prompt=prompt,
            model=model or self.config.model.default,
            effort=effort,
            web_search=web_search,
            files=files or [],
            depends_on=depends_on or [],
            metadata=metadata,
        )

        self._tasks[task_id] = task
        self._persist_task(task)

        # Build dependency graph
        for dep_id in task.depends_on:
            self._dependency_graph[task_id].add(dep_id)
            self._reverse_deps[dep_id].add(task_id)

        # Check if ready to run
        if self._is_ready(task_id):
            task.status = TaskStatus.QUEUED
            await self._queue.put(task_id)
        else:
            task.status = TaskStatus.PENDING
        self._persist_task(task)

        await self._emit(EventType.TASK_CREATED, self._task_event_payload(task))
        logger.info("task_submitted", task_id=task_id, name=name, deps=task.depends_on)

        return task

    async def status(self, task_id: str | None = None) -> dict[str, Any]:
        """Get status of all tasks or a specific task."""
        if task_id:
            task = self._tasks.get(task_id)
            if not task:
                return {"error": f"Task {task_id} not found"}
            return self._task_to_dict(task)

        scheduled_waiting = max(0, len(self._running_tasks) - len(self._active_task_ids))
        return {
            "tasks": [self._task_to_dict(t) for t in self._tasks.values()],
            "running": len(self._active_task_ids),
            "queued": self._queue.qsize() + scheduled_waiting,
            "scheduled_waiting": scheduled_waiting,
            "max_parallel": self.task_config.max_parallel,
        }

    async def cancel(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if not task or task.is_terminal:
            return False

        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()

        task.status = TaskStatus.CANCELLED
        self._persist_task(task)
        await self._emit(EventType.TASK_CANCELLED, self._task_event_payload(task))
        return True

    def _is_ready(self, task_id: str) -> bool:
        """Check if all dependencies are satisfied."""
        task = self._tasks[task_id]
        for dep_id in task.depends_on:
            dep = self._tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def _generate_task_id(self, name: str) -> str:
        """Generate a unique task ID."""
        timestamp = str(time.time())
        hash_input = f"{name}-{timestamp}"
        return f"{name.lower().replace(' ', '-')}-{hashlib.md5(hash_input.encode()).hexdigest()[:8]}"

    def _create_worktree(self, task: Task) -> str:
        """Create a git worktree for isolated task execution."""
        if not self.task_config.use_git_worktree or not self._repo:
            # Use temp directory
            wt_path = tempfile.mkdtemp(prefix=f"fugu-{task.task_id}-")
            task.branch = f"fugu-task-{task.task_id}"
            return wt_path

        # Create branch and worktree
        branch_name = f"fugu-task-{task.task_id}"
        wt_path = self._repo_root / ".fugu-worktrees" / task.task_id
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Create branch from main
            main_branch = self.task_config.git_default_branch
            self._repo.create_head(branch_name, getattr(self._repo.heads, main_branch))

            # Create worktree
            self._repo.git.worktree("add", str(wt_path), branch_name)
            task.branch = branch_name

        except GitCommandError as e:
            logger.warning("worktree_creation_failed", error=str(e))
            # Fallback to temp
            wt_path = Path(tempfile.mkdtemp(prefix=f"fugu-{task.task_id}-"))

        return str(wt_path)

    def _load_persisted_tasks(self) -> None:
        for path in self._state_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                task = Task(
                    task_id=data["task_id"],
                    name=data.get("name", ""),
                    description=data.get("description", ""),
                    prompt=data.get("prompt", ""),
                    model=data.get("model", self.config.model.default),
                    effort=data.get("effort", self.config.model.reasoning_effort),
                    web_search=data.get("web_search", False),
                    files=data.get("files", []),
                    depends_on=data.get("depends_on", []),
                    branch=data.get("branch", ""),
                    worktree_path=data.get("worktree", ""),
                    status=TaskStatus(data.get("status", "pending")),
                    output=data.get("output", ""),
                    error=data.get("error", ""),
                    token_usage=data.get("token_usage", {}),
                    metadata=data.get("metadata", {}),
                )
                for attr in ("created_at", "started_at", "completed_at"):
                    value = data.get(attr)
                    if value:
                        setattr(task, attr, datetime.fromisoformat(value))
                output_path = self._task_output_path(task.task_id)
                if output_path.exists():
                    task.output = output_path.read_text(encoding="utf-8")
                self._tasks[task.task_id] = task
            except Exception as e:
                logger.warning("task_state_load_failed", path=str(path), error=str(e))

    async def _recover_interrupted_tasks(self) -> None:
        """Resume queued tasks and mark orphaned running tasks as failed."""
        for task_id, task in self._tasks.items():
            if task.status == TaskStatus.RUNNING:
                if self._run_scheduler:
                    task.status = TaskStatus.QUEUED
                    task.started_at = None
                    task.completed_at = None
                    task.error = ""
                    self._persist_task(task)
                    await self._queue.put(task_id)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = task.error or "Interrupted while running; submit again to retry."
                    task.completed_at = task.completed_at or datetime.now()
                    self._persist_task(task)
            elif task.status == TaskStatus.QUEUED or (
                task.status == TaskStatus.PENDING and self._is_ready(task_id)
            ):
                task.status = TaskStatus.QUEUED
                self._persist_task(task)
                await self._queue.put(task_id)


    def _persist_task(self, task: Task) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_dir / f"{task.task_id}.json"
        data = self._task_to_dict(task)
        data.update(
            {
                "prompt": task.prompt,
                "web_search": task.web_search,
                "files": task.files,
                "output": task.output,
                "error": task.error,
                "metadata": task.metadata,
            }
        )
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)

    def _append_task_output(self, task: Task, content: str) -> None:
        """Append live task output for attach/recovery."""
        if not content:
            return
        output_path = self._task_output_path(task.task_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as f:
            f.write(content)

    def _task_output_path(self, task_id: str) -> Path:
        return self._state_dir / f"{task_id}.output.txt"

    def _merge_worktree(self, task: Task) -> bool:
        """Merge completed task back to main branch."""
        if not self.task_config.auto_merge or not task.branch:
            return False

        try:
            # Switch to main and merge
            main_branch = self.task_config.git_default_branch
            main = getattr(self._repo.heads, main_branch)
            self._repo.head.reference = main
            self._repo.git.merge(task.branch, no_ff=True, m=f"Merge fugu task: {task.name}")

            # Clean up worktree
            self._repo.git.worktree("remove", task.worktree_path, force=True)

            task.status = TaskStatus.MERGED
            logger.info("task_merged", task_id=task.task_id)
            return True

        except GitCommandError as e:
            logger.error("merge_failed", task_id=task.task_id, error=str(e))
            return False

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop processing the task queue."""
        while self._running:
            try:
                task_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)

                if task_id in self._tasks and not self._tasks[task_id].is_terminal:
                    self._running_tasks[task_id] = asyncio.create_task(
                        self._execute_task_with_slot(task_id)
                    )

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("scheduler_error")


    async def _execute_task_with_slot(self, task_id: str) -> None:
        """Execute a queued task while holding a concurrency slot."""
        if self._semaphore is None:
            await self._execute_task(task_id)
            return
        async with self._semaphore:
            self._active_task_ids.add(task_id)
            try:
                await self._execute_task(task_id)
            finally:
                self._active_task_ids.discard(task_id)

    async def _execute_task(self, task_id: str) -> None:
        """Execute a single Fugu task."""
        task = self._tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._persist_task(task)

        await self._emit(EventType.TASK_STARTED, self._task_event_payload(task))

        try:
            task.worktree_path = self._create_worktree(task)
            workspace = Path(task.worktree_path)
            attachment_paths = [Path(file_path) for file_path in task.files]
            content = build_content_parts(task.prompt, attachment_paths) if attachment_paths else task.prompt
            messages = [{"role": "user", "content": content}]
            from fugu_vibe.agent.loop import AgentLoop
            from fugu_vibe.core.headless import build_headless_registry
            from fugu_vibe.core.instructions import build_instructions
            from fugu_vibe.core.orchestration import OrchestrationAnalyzer

            output_parts: list[str] = []

            def on_content(content_piece: str) -> None:
                if not content_piece:
                    return
                output_parts.append(content_piece)
                self._append_task_output(task, content_piece)
                if self.event_bus:
                    asyncio.create_task(
                        self._emit(
                            EventType.STREAM_CONTENT,
                            {"task_id": task_id, "content": content_piece},
                        )
                    )
                    asyncio.create_task(
                        self._emit(
                            EventType.TASK_PROGRESS,
                            {
                                **self._task_event_payload(task),
                                "output_length": len("".join(output_parts)),
                            },
                        )
                    )

            registry = build_headless_registry(self.config, workspace)
            analyzer = OrchestrationAnalyzer(self.config, self.event_bus)
            loop = AgentLoop(
                self.client,
                registry,
                self.event_bus or EventBus(),
                max_tool_rounds=self.config.tools.max_tool_rounds,
                auto_test_after_edit=self.config.tools.auto_test_after_edit,
                auto_test_command=self.config.tools.auto_test_command,
                auto_compile_after_edit=self.config.tools.auto_compile_after_edit,
                auto_lint_after_edit=self.config.tools.auto_lint_after_edit,
                auto_lint_command=self.config.tools.auto_lint_command,
            )
            result = await loop.run(
                messages=messages,
                model=task.model,
                effort=task.effort,  # type: ignore[arg-type]
                web_search=task.web_search,
                instructions=build_instructions(TASK_AGENT_INSTRUCTIONS, workspace),
                max_output_tokens=min(self.config.model.max_output_tokens, 4096),
                on_content=on_content,
                on_chunk=analyzer.analyze_chunk,
            )
            await analyzer.finalize()

            task.output = "".join(output_parts) or result.content
            task.token_usage = {
                "input": analyzer.state.token_usage.input_tokens,
                "output": analyzer.state.token_usage.output_tokens,
                "orchestration": analyzer.state.token_usage.orchestration_tokens,
                "total": analyzer.state.token_usage.total_tokens,
            }
            task.metadata.update(
                {
                    "rounds": result.rounds,
                    "tool_calls": result.tool_calls,
                    "tool_call_count": len(result.tool_calls),
                    "automatic_verification": result.automatic_verification,
                    "orchestration": {
                        "workers": len(analyzer.state.workers),
                        "verifications": analyzer.state.verification_count,
                        "routing_confidence": analyzer.state.routing_confidence,
                    },
                }
            )
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            self._persist_task(task)

            if self.task_config.auto_merge:
                self._merge_worktree(task)
                self._persist_task(task)

            await self._emit(EventType.TASK_COMPLETED, self._task_event_payload(task))
            await self._wake_dependents(task_id)

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            raise
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            self._persist_task(task)
            await self._emit(EventType.TASK_FAILED, self._task_event_payload(task))
            logger.error("task_failed", task_id=task_id, error=str(e))
        finally:
            self._running_tasks.pop(task_id, None)
            self._active_task_ids.discard(task_id)

    async def _wake_dependents(self, completed_task_id: str) -> None:
        """Check and queue tasks that were waiting on the completed task."""
        for dependent_id in self._reverse_deps[completed_task_id]:
            if dependent_id in self._tasks:
                task = self._tasks[dependent_id]
                if task.status == TaskStatus.PENDING and self._is_ready(dependent_id):
                    task.status = TaskStatus.QUEUED
                    self._persist_task(task)
                    await self._queue.put(dependent_id)

    async def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit event to bus."""
        if self.event_bus:
            await self.event_bus.emit(event_type, data, source="task_manager")

    def _task_to_dict(self, task: Task) -> dict[str, Any]:
        """Convert task to dictionary representation."""
        return {
            **self._task_event_payload(task),
            "description": task.description,
            "output": task.output,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }

    def _task_event_payload(self, task: Task) -> dict[str, Any]:
        """Compact task payload for live events, status, and dashboards."""
        metadata = task.metadata or {}
        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "model": task.model,
            "effort": task.effort,
            "depends_on": task.depends_on,
            "branch": task.branch,
            "worktree": task.worktree_path,
            "duration": task.duration,
            "token_usage": task.token_usage,
            "rounds": metadata.get("rounds", 0),
            "tool_call_count": metadata.get("tool_call_count", 0),
            "tool_calls": metadata.get("tool_calls", []),
            "automatic_verification": metadata.get("automatic_verification", {}),
            "orchestration": metadata.get("orchestration", {}),
            "metadata": metadata,
        }
