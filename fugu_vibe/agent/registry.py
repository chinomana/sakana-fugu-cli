"""Local tool registry for Fugu Responses function calls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fugu_vibe.tools import FileTools, FileToolError


@dataclass
class ToolRegistry:
    """Register and dispatch local tools."""

    file_tools: FileTools

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "file_list",
                "description": "List files in the current workspace. Read-only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "default": "**/*"},
                        "limit": {"type": "integer", "default": 200},
                    },
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "type": "function",
                "name": "file_read",
                "description": "Read a UTF-8 text file from the workspace. Read-only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "default": 1},
                        "limit": {"type": "integer", "default": 200},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "type": "function",
                "name": "file_search",
                "description": "Search UTF-8 workspace files for a literal query. Read-only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "pattern": {"type": "string", "default": "**/*"},
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "type": "function",
                "name": "file_write",
                "description": "Create or overwrite a UTF-8 text file in the current workspace. Use for implementation tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean", "default": True},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "type": "function",
                "name": "file_mkdir",
                "description": "Create a directory in the current workspace. Use before writing grouped project files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        ]

    async def dispatch(self, name: str, arguments: str | dict[str, Any]) -> dict[str, Any]:
        name = name.replace(".", "_")
        args = self._parse_arguments(arguments)
        try:
            if name == "file_list":
                files = self.file_tools.list_files(
                    pattern=str(args.get("pattern", "**/*")),
                    limit=int(args.get("limit", 200)),
                )
                return {"ok": True, "files": files, "count": len(files)}
            if name == "file_read":
                content = self.file_tools.read_file(
                    Path(str(args["path"])),
                    start_line=int(args.get("start_line", 1)),
                    limit=int(args.get("limit", 200)),
                )
                return {"ok": True, "path": str(args["path"]), "content": content}
            if name == "file_search":
                matches = self.file_tools.search(
                    query=str(args["query"]),
                    pattern=str(args.get("pattern", "**/*")),
                    limit=int(args.get("limit", 50)),
                )
                return {"ok": True, "matches": matches, "count": len(matches)}
            if name == "file_write":
                overwrite = args.get("overwrite", True)
                if isinstance(overwrite, str):
                    overwrite = overwrite.lower() in ("1", "true", "yes")
                path = self.file_tools.write_file(
                    Path(str(args["path"])),
                    content=str(args["content"]),
                    overwrite=bool(overwrite),
                )
                return {"ok": True, "path": path, "bytes": len(str(args["content"]).encode("utf-8"))}
            if name == "file_mkdir":
                path = self.file_tools.make_directory(Path(str(args["path"])))
                return {"ok": True, "path": path}
        except (KeyError, ValueError, FileToolError) as e:
            return {"ok": False, "error": str(e)}

        return {"ok": False, "error": f"Unknown tool: {name}"}

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
