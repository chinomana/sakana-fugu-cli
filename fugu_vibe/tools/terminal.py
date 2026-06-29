"""Workspace-safe terminal command execution."""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fugu_vibe.safety import SafetyMode, SafetyPolicy


class TerminalToolError(Exception):
    """Raised when terminal execution is disabled or unsafe."""


@dataclass
class TerminalResult:
    """Result of a terminal command."""

    run_id: str
    command: str
    cwd: Path
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    log_path: Path
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a structured, JSON-serializable result."""
        return {
            "run_id": self.run_id,
            "command": self.command,
            "cwd": str(self.cwd),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "log_path": str(self.log_path),
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
        }


@dataclass
class TerminalTool:
    """Run shell commands constrained to a workspace."""

    workspace: Path
    enabled: bool = False
    approval: str = "off"
    safety_mode: str | SafetyMode | None = None
    timeout_seconds: int = 120
    max_output_chars: int = 20_000

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()
        self.log_dir = self.workspace / ".fugu-vibe" / "tool-runs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.safety_policy = SafetyPolicy(self.safety_mode or self.approval)

    def status(self) -> dict[str, Any]:
        return {
            "terminal_enabled": self.enabled,
            "terminal_approval": self.approval,
            "safety_mode": self.safety_policy.mode.value,
            "timeout_seconds": self.timeout_seconds,
            "max_output_chars": self.max_output_chars,
        }

    async def run(self, command: str, cwd: str | Path | None = None, *, approved: bool = False) -> TerminalResult:
        """Run a shell command after policy checks."""
        if not self.enabled or (self.approval == "off" and self.safety_mode is None):
            raise TerminalToolError("Terminal tools are disabled. Enable tools.terminal_enabled first.")
        self._check_command(command, approved=approved)
        resolved_cwd = self._resolve_cwd(cwd)

        started = datetime.now()
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(resolved_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        finished = datetime.now()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        run_id = uuid4().hex[:12]
        log_path = self._write_log(
            run_id=run_id,
            command=command,
            cwd=resolved_cwd,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=(finished - started).total_seconds(),
            timed_out=timed_out,
        )
        truncated_stdout, stdout_truncated = self._truncate(stdout)
        truncated_stderr, stderr_truncated = self._truncate(stderr)
        return TerminalResult(
            run_id=run_id,
            command=command,
            cwd=resolved_cwd,
            exit_code=process.returncode,
            stdout=truncated_stdout,
            stderr=truncated_stderr,
            duration_seconds=(finished - started).total_seconds(),
            timed_out=timed_out,
            log_path=log_path,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    async def run_structured(
        self,
        command: str,
        cwd: str | Path | None = None,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Run a command and return a JSON-serializable result."""
        return (await self.run(command, cwd=cwd, approved=approved)).to_dict()

    def _check_command(self, command: str, *, approved: bool = False) -> None:
        normalized = " ".join(command.strip().split())
        if not normalized:
            raise TerminalToolError("Command must not be empty")
        decision = self.safety_policy.evaluate_command(normalized, approved=approved)
        if not decision.allowed:
            raise TerminalToolError(decision.reason)

    def _resolve_cwd(self, cwd: str | Path | None) -> Path:
        if cwd is None:
            return self.workspace
        path = Path(cwd).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if not resolved.is_dir():
            raise TerminalToolError(f"cwd is not a directory: {cwd}")
        if not resolved.is_relative_to(self.workspace):
            raise TerminalToolError(f"cwd escapes workspace: {cwd}")
        return resolved

    def _truncate(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_output_chars:
            return text, False
        omitted = len(text) - self.max_output_chars
        return text[: self.max_output_chars] + f"\n...[truncated {omitted} chars]", True

    def _write_log(
        self,
        run_id: str,
        command: str,
        cwd: Path,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_seconds: float,
        timed_out: bool,
    ) -> Path:
        log_path = self.log_dir / f"{run_id}.json"
        data = {
            "run_id": run_id,
            "command": command,
            "argv_preview": shlex.split(command) if command else [],
            "cwd": str(cwd),
            "exit_code": exit_code,
            "duration_seconds": duration_seconds,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "created_at": datetime.now().isoformat(),
        }
        tmp_path = log_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(log_path)
        return log_path
