"""Local tool registry for Fugu Responses function calls."""

from __future__ import annotations

import difflib
import json
import re
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fugu_vibe.mcp import MCPToolManager
from fugu_vibe.tools import (
    FileToolError,
    FileTools,
    GitToolError,
    GitTools,
    TerminalTool,
    TerminalToolError,
)

ApprovalCallback = Callable[[str, dict[str, Any], str], Awaitable[bool]]


@dataclass
class ToolRegistry:
    """Register and dispatch local tools."""

    file_tools: FileTools
    terminal_tool: TerminalTool | None = None
    git_tools: GitTools | None = None
    approval_callback: ApprovalCallback | None = None
    mcp_tools: MCPToolManager | None = None

    def has_tool(self, name: str) -> bool:
        return any(schema.get("name") == name for schema in self.schemas())

    def schemas(self) -> list[dict[str, Any]]:
        schemas = [
            self._schema(
                "file_list",
                "List workspace files with size and modified-time metadata. Read-only.",
                {
                    "pattern": {"type": "string", "default": "**/*"},
                    "limit": {"type": "integer", "default": 200},
                },
            ),
            self._schema(
                "file_glob",
                "Find workspace files by glob pattern with structured metadata. Read-only.",
                {
                    "pattern": {"type": "string", "default": "**/*"},
                    "limit": {"type": "integer", "default": 200},
                },
            ),
            self._schema(
                "file_read",
                "Read a UTF-8 text file with line metadata. Read-only.",
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "default": 1},
                    "limit": {"type": "integer", "default": 200},
                },
                required=["path"],
            ),
            self._schema(
                "file_search",
                "Search UTF-8 workspace files for a literal query or regular expression. Read-only.",
                {
                    "query": {"type": "string"},
                    "pattern": {"type": "string", "default": "**/*"},
                    "limit": {"type": "integer", "default": 50},
                    "regex": {"type": "boolean", "default": False},
                },
                required=["query"],
            ),
            self._schema(
                "file_grep",
                "Search workspace files with a regular expression. Read-only alias for file_search(regex=true).",
                {
                    "pattern_regex": {"type": "string"},
                    "file_glob": {"type": "string", "default": "**/*"},
                    "limit": {"type": "integer", "default": 50},
                },
                required=["pattern_regex"],
            ),
            self._schema(
                "file_write",
                "Create or overwrite a UTF-8 text file in the current workspace.",
                {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": True},
                },
                required=["path", "content"],
            ),
            self._schema(
                "file_edit",
                "Replace an exact string in a UTF-8 text file without rewriting the whole file.",
                {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean", "default": False},
                },
                required=["path", "old_string", "new_string"],
            ),
            self._schema(
                "file_delete",
                "Delete a file from the current workspace.",
                {"path": {"type": "string"}},
                required=["path"],
            ),
            self._schema(
                "file_mkdir",
                "Create a directory in the current workspace.",
                {"path": {"type": "string"}},
                required=["path"],
            ),
        ]
        if self.terminal_tool is not None:
            schemas.extend(
                [
                    self._schema(
                        "bash",
                        "Run a shell command in the workspace and return structured stdout/stderr/exit-code data.",
                        {
                            "command": {"type": "string"},
                            "cwd": {"type": "string", "default": "."},
                        },
                        required=["command"],
                    ),
                    self._schema(
                        "run_test",
                        "Run the project's test command and return a structured test summary.",
                        {
                            "command": {"type": "string", "default": "pytest"},
                            "cwd": {"type": "string", "default": "."},
                        },
                    ),
                    self._schema(
                        "run_lint",
                        "Run the project's lint/type-check command and return structured results.",
                        {
                            "command": {"type": "string", "default": "ruff check ."},
                            "cwd": {"type": "string", "default": "."},
                        },
                    ),
                ]
            )
        if self.git_tools is not None:
            schemas.extend(
                [
                    self._schema("git_status", "Return structured git status. Read-only.", {}),
                    self._schema(
                        "git_diff",
                        "Return git diff text and metadata. Read-only.",
                        {
                            "path": {"type": "string", "default": ""},
                            "cached": {"type": "boolean", "default": False},
                        },
                    ),
                    self._schema(
                        "git_log",
                        "Return recent commits. Read-only.",
                        {"limit": {"type": "integer", "default": 10}},
                    ),
                    self._schema(
                        "git_show",
                        "Show a commit or revision with stat and patch. Read-only.",
                        {"revision": {"type": "string", "default": "HEAD"}},
                    ),
                ]
            )
        if self.mcp_tools is not None:
            schemas.extend(self.mcp_tools.schemas())
        return schemas

    async def approve_file_operation(self, name: str, args: dict[str, Any]) -> bool:
        preview = self._file_operation_preview(name, args)
        if self.file_tools.safety_policy.evaluate_file_write(str(args.get("path", ""))).allowed:
            return True
        if self.approval_callback is None:
            return False
        return await self.approval_callback(name, args, preview)

    async def approve_terminal_operation(self, name: str, args: dict[str, Any]) -> bool:
        command = str(args.get("command", ""))
        if self.terminal_tool is None:
            return False
        if self.terminal_tool.safety_policy.evaluate_command(command).allowed:
            return True
        if self.approval_callback is None:
            return False
        preview = f"$ {command}\n"
        return await self.approval_callback(name, args, preview)

    async def dispatch(self, name: str, arguments: str | dict[str, Any]) -> dict[str, Any]:
        name = name.replace(".", "_")
        args = self._parse_arguments(arguments)
        try:
            if name in {"file_list", "file_glob"}:
                return {
                    "ok": True,
                    **self.file_tools.glob_files(
                        pattern=str(args.get("pattern", "**/*")),
                        limit=int(args.get("limit", 200)),
                    ),
                }
            if name == "file_read":
                return {
                    "ok": True,
                    **self.file_tools.read_file_structured(
                        Path(str(args["path"])),
                        start_line=int(args.get("start_line", 1)),
                        limit=int(args.get("limit", 200)),
                    ),
                }
            if name == "file_search":
                return {
                    "ok": True,
                    **self.file_tools.search_structured(
                        query=str(args["query"]),
                        pattern=str(args.get("pattern", "**/*")),
                        limit=int(args.get("limit", 50)),
                        regex=self._bool_arg(args.get("regex", False)),
                    ),
                }
            if name == "file_grep":
                return {
                    "ok": True,
                    **self.file_tools.search_structured(
                        query=str(args["pattern_regex"]),
                        pattern=str(args.get("file_glob", "**/*")),
                        limit=int(args.get("limit", 50)),
                        regex=True,
                    ),
                }
            if name == "file_write":
                approved = await self.approve_file_operation(name, args)
                return {
                    "ok": True,
                    **self.file_tools.write_file_structured(
                        Path(str(args["path"])),
                        content=str(args["content"]),
                        overwrite=self._bool_arg(args.get("overwrite", True)),
                        approved=approved,
                    ),
                }
            if name == "file_edit":
                approved = await self.approve_file_operation(name, args)
                return {
                    "ok": True,
                    **self.file_tools.edit_file(
                        Path(str(args["path"])),
                        old_string=str(args["old_string"]),
                        new_string=str(args["new_string"]),
                        replace_all=self._bool_arg(args.get("replace_all", False)),
                        approved=approved,
                    ),
                }
            if name == "file_delete":
                approved = await self.approve_file_operation(name, args)
                return {
                    "ok": True,
                    **self.file_tools.delete_file(Path(str(args["path"])), approved=approved),
                }
            if name == "file_mkdir":
                approved = await self.approve_file_operation(name, args)
                path = self.file_tools.make_directory(Path(str(args["path"])), approved=approved)
                return {"ok": True, "path": path}
            if name == "bash":
                approved = await self.approve_terminal_operation(name, args)
                result = await self._run_terminal(
                    str(args["command"]), str(args.get("cwd", ".")), approved=approved
                )
                return {"ok": result["exit_code"] == 0 and not result["timed_out"], **result}
            if name == "run_test":
                approved = await self.approve_terminal_operation(name, args)
                result = await self._run_terminal(
                    str(args.get("command", "pytest")),
                    str(args.get("cwd", ".")),
                    approved=approved,
                )
                summary = self._summarize_tests(result)
                return {
                    "ok": result["exit_code"] == 0 and not result["timed_out"],
                    **result,
                    "summary": summary,
                    "failures": self._extract_test_failures(result),
                    "output_truncated": result.get("stdout_truncated", False)
                    or result.get("stderr_truncated", False),
                }
            if name == "run_lint":
                approved = await self.approve_terminal_operation(name, args)
                result = await self._run_terminal(
                    str(args.get("command", "ruff check .")),
                    str(args.get("cwd", ".")),
                    approved=approved,
                )
                return {"ok": result["exit_code"] == 0 and not result["timed_out"], **result}
            if name == "git_status":
                return {"ok": True, **self._git().status()}
            if name == "git_diff":
                path = str(args.get("path", "")) or None
                return {
                    "ok": True,
                    **self._git().diff(path=path, cached=self._bool_arg(args.get("cached", False))),
                }
            if name == "git_log":
                return {"ok": True, **self._git().log(limit=int(args.get("limit", 10)))}
            if name == "git_show":
                return {"ok": True, **self._git().show(revision=str(args.get("revision", "HEAD")))}
            if name == "mcp_list_tools" and self.mcp_tools is not None:
                return {
                    "ok": True,
                    **await self.mcp_tools.list_tools(str(args.get("server") or "") or None),
                }
            if name == "mcp_call" and self.mcp_tools is not None:
                return await self.mcp_tools.call_tool(
                    str(args["server"]),
                    str(args["tool"]),
                    args.get("arguments") if isinstance(args.get("arguments"), dict) else {},
                )
        except (KeyError, ValueError, FileToolError, TerminalToolError, GitToolError) as e:
            return self._tool_error(name, e, args)

        return {
            "ok": False,
            "error": f"Unknown tool: {name}",
            "tool": name,
            "error_type": "unknown_tool",
            "retryable": False,
        }

    def _tool_error(self, name: str, error: Exception, args: dict[str, Any]) -> dict[str, Any]:
        error_type = type(error).__name__
        message = str(error)
        retryable = isinstance(error, TerminalToolError) and any(
            marker in message.lower() for marker in ("timed out", "timeout", "temporarily")
        )
        return {
            "ok": False,
            "tool": name,
            "error": message,
            "error_type": error_type,
            "retryable": retryable,
            "arguments": self._safe_error_arguments(args),
            "traceback_tail": traceback.format_exception_only(type(error), error)[-1].strip(),
        }

    def _safe_error_arguments(self, args: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in args.items():
            if key in {"content", "new_string", "old_string"}:
                safe[key] = f"<{len(str(value))} chars>"
            else:
                safe[key] = value
        return safe

    def _schema(
        self,
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        schema = {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
            "strict": True,
        }
        if required:
            schema["parameters"]["required"] = required
        return schema

    def _file_operation_preview(self, name: str, args: dict[str, Any]) -> str:
        path = str(args.get("path", ""))
        if name == "file_write":
            return self._write_preview(path, str(args.get("content", "")))
        if name == "file_edit":
            return self._edit_preview(
                path,
                str(args.get("old_string", "")),
                str(args.get("new_string", "")),
                self._bool_arg(args.get("replace_all", False)),
            )
        if name == "file_delete":
            return self._delete_preview(path)
        if name == "file_mkdir":
            return f"Create directory: {path}\n"
        return f"{name} {path}\n"

    def _write_preview(self, path: str, content: str) -> str:
        resolved = self._resolve_preview_path(path)
        old_lines = (
            resolved.read_text(encoding="utf-8").splitlines(keepends=True)
            if resolved.exists()
            else []
        )
        new_lines = content.splitlines(keepends=True)
        if content and not content.endswith("\n"):
            new_lines[-1] = f"{new_lines[-1]}\n"
        return "".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{path}" if old_lines else "/dev/null",
                tofile=f"b/{path}",
            )
        )

    def _edit_preview(self, path: str, old_string: str, new_string: str, replace_all: bool) -> str:
        resolved = self._resolve_preview_path(path)
        old_content = resolved.read_text(encoding="utf-8") if resolved.exists() else ""
        count = old_content.count(old_string) if old_string else 0
        replacements = count if replace_all else min(count, 1)
        new_content = (
            old_content.replace(old_string, new_string, replacements)
            if replacements
            else old_content
        )
        return "".join(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )

    def _delete_preview(self, path: str) -> str:
        resolved = self._resolve_preview_path(path)
        old_content = resolved.read_text(encoding="utf-8") if resolved.exists() else ""
        return "".join(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                [],
                fromfile=f"a/{path}",
                tofile="/dev/null",
            )
        )

    def _resolve_preview_path(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.file_tools.workspace / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.file_tools.workspace):
            raise FileToolError(f"Path escapes workspace: {path}")
        return resolved

    def _parse_arguments(self, arguments: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if not arguments:
            return {}
        try:
            data = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _bool_arg(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    async def _run_terminal(
        self, command: str, cwd: str = ".", *, approved: bool = False
    ) -> dict[str, Any]:
        if self.terminal_tool is None:
            raise TerminalToolError("Terminal tool is not configured")
        return await self.terminal_tool.run_structured(command, cwd=cwd, approved=approved)

    def _git(self) -> GitTools:
        if self.git_tools is None:
            raise GitToolError("Git tools are not configured")
        return self.git_tools

    def _summarize_tests(self, result: dict[str, Any]) -> dict[str, Any]:
        output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
        summary: dict[str, Any] = {"passed": None, "failed": None, "errors": None, "skipped": None}
        patterns = {
            "passed": r"(\d+) passed",
            "failed": r"(\d+) failed",
            "errors": r"(\d+) errors?",
            "skipped": r"(\d+) skipped",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                summary[key] = int(match.group(1))
        known_counts = [value for value in summary.values() if isinstance(value, int)]
        summary["total"] = sum(known_counts) if known_counts else None
        summary["status"] = "passed" if result.get("exit_code") == 0 else "failed"
        return summary

    def _extract_test_failures(
        self, result: dict[str, Any], limit: int = 5
    ) -> list[dict[str, str]]:
        output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
        failures: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        for line in output.splitlines():
            failed_match = re.match(r"_{2,}\s+(.+?)\s+_{2,}$", line.strip())
            short_match = re.match(r"FAILED\s+([^\s]+)\s+-\s+(.+)", line.strip())
            if failed_match:
                current = {"test": failed_match.group(1), "error": "", "snippet": ""}
                failures.append(current)
                if len(failures) >= limit:
                    break
                continue
            if short_match:
                failures.append(
                    {
                        "test": short_match.group(1),
                        "error": short_match.group(2),
                        "snippet": line.strip(),
                    }
                )
                if len(failures) >= limit:
                    break
                continue
            if current is not None and ("AssertionError" in line or line.startswith("E   ")):
                current["error"] = (current.get("error", "") + " " + line.strip()).strip()
            if current is not None and line.startswith((">", "E   ")):
                current["snippet"] = (current.get("snippet", "") + "\n" + line).strip()
        return failures[:limit]
