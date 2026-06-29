"""Workspace-safe file tools."""

from __future__ import annotations

import fnmatch
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Any

from fugu_vibe.safety import SafetyMode, SafetyPolicy

DEFAULT_EXCLUDES = {
    ".git",
    ".fugu-vibe",
    ".fugu-worktrees",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv312",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
}

MAX_READ_BYTES = 512 * 1024
MAX_SEARCH_BYTES = 256 * 1024
MAX_WRITE_BYTES = 512 * 1024
DEFAULT_READ_LINES = 200
MAX_READ_LINES = 500
MAX_LIST_LIMIT = 2_000


class FileToolError(Exception):
    """Raised when a file tool request is invalid or unsafe."""


@dataclass
class FileTools:
    """File operations constrained to one workspace."""

    workspace: Path
    safety_mode: str | SafetyMode = SafetyMode.AUTO_EDIT

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()
        self.safety_policy = SafetyPolicy(self.safety_mode)

    def require_write_allowed(self, path: str | Path | None = None, *, approved: bool = False) -> None:
        """Raise if the current safety mode does not allow file mutation."""
        relative_path = None if path is None else str(path)
        decision = self.safety_policy.evaluate_file_write(relative_path, approved=approved)
        if not decision.allowed:
            raise FileToolError(decision.reason)

    def list_files(self, pattern: str = "**/*", limit: int = 200) -> list[str]:
        """List workspace files matching a glob pattern."""
        return [entry["path"] for entry in self.list_file_entries(pattern, limit)["files"]]

    def list_file_entries(self, pattern: str = "**/*", limit: int = 200) -> dict[str, Any]:
        """List matching workspace files with metadata."""
        limit = self._normalize_limit(limit, MAX_LIST_LIMIT)
        files: list[dict[str, Any]] = []
        truncated = False
        for path in sorted(self.workspace.glob(pattern)):
            if len(files) >= limit:
                truncated = True
                break
            if not path.is_file() or self._is_excluded(path):
                continue
            stat = path.stat()
            files.append(
                {
                    "path": self._relative(path),
                    "type": "file",
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
        return {"files": files, "count": len(files), "truncated": truncated, "pattern": pattern}

    def glob_files(self, pattern: str = "**/*", limit: int = 200) -> dict[str, Any]:
        """Find files by glob pattern and return structured metadata."""
        return self.list_file_entries(pattern, limit)

    def read_file(
        self,
        path: str | Path,
        max_bytes: int = MAX_READ_BYTES,
        start_line: int = 1,
        limit: int | None = None,
    ) -> str:
        """Read a UTF-8 text file from the workspace."""
        result = self.read_file_structured(path, max_bytes=max_bytes, start_line=start_line, limit=limit)
        return str(result["content"])

    def read_file_structured(
        self,
        path: str | Path,
        max_bytes: int = MAX_READ_BYTES,
        start_line: int = 1,
        limit: int | None = DEFAULT_READ_LINES,
    ) -> dict[str, Any]:
        """Read a UTF-8 text file and include line metadata."""
        resolved = self._resolve_text_file(path, max_bytes=max_bytes)
        if start_line < 1:
            raise FileToolError("start_line must be >= 1")
        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise FileToolError(f"File is not UTF-8 text: {path}") from e

        all_lines = content.splitlines()
        if limit is None:
            selected = all_lines[start_line - 1 :]
        else:
            limit = self._normalize_limit(limit, MAX_READ_LINES)
            selected = all_lines[start_line - 1 : start_line - 1 + limit]
        start_index = start_line - 1
        line_items = [
            {"line": start_index + offset + 1, "text": line}
            for offset, line in enumerate(selected)
        ]
        end_line = line_items[-1]["line"] if line_items else start_line - 1
        selected_content = "\n".join(selected) + ("\n" if selected else "")
        return {
            "path": self._relative(resolved),
            "content": selected_content,
            "lines": line_items,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": len(all_lines),
            "size_bytes": resolved.stat().st_size,
            "encoding": "utf-8",
            "truncated": end_line < len(all_lines),
        }

    def search(
        self,
        query: str,
        pattern: str = "**/*",
        limit: int = 50,
        max_file_bytes: int = MAX_SEARCH_BYTES,
        regex: bool = False,
    ) -> list[dict[str, str | int]]:
        """Search UTF-8 workspace files for a literal query or regular expression."""
        return self.search_structured(
            query=query,
            pattern=pattern,
            limit=limit,
            max_file_bytes=max_file_bytes,
            regex=regex,
        )["matches"]

    def search_structured(
        self,
        query: str,
        pattern: str = "**/*",
        limit: int = 50,
        max_file_bytes: int = MAX_SEARCH_BYTES,
        regex: bool = False,
    ) -> dict[str, Any]:
        """Search UTF-8 workspace files and return structured matches."""
        if not query:
            raise FileToolError("Search query must not be empty")
        limit = self._normalize_limit(limit, MAX_LIST_LIMIT)
        compiled = self._compile_regex(query) if regex else None

        matches: list[dict[str, str | int]] = []
        truncated = False
        for path in sorted(self.workspace.glob(pattern)):
            if len(matches) >= limit:
                truncated = True
                break
            if not path.is_file() or self._is_excluded(path):
                continue
            if path.stat().st_size > max_file_bytes:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                column = self._match_column(line, query, compiled)
                if column is None:
                    continue
                matches.append(
                    {
                        "path": self._relative(path),
                        "line": line_number,
                        "column": column,
                        "text": line.strip(),
                    }
                )
                if len(matches) >= limit:
                    break
        return {
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
            "query": query,
            "pattern": pattern,
            "regex": regex,
        }

    def write_file(
        self,
        path: str | Path,
        content: str,
        overwrite: bool = True,
        max_bytes: int = MAX_WRITE_BYTES,
        approved: bool = False,
    ) -> str:
        """Write a UTF-8 text file inside the workspace."""
        return str(
            self.write_file_structured(
                path=path,
                content=content,
                overwrite=overwrite,
                max_bytes=max_bytes,
                approved=approved,
            )["path"]
        )

    def write_file_structured(
        self,
        path: str | Path,
        content: str,
        overwrite: bool = True,
        max_bytes: int = MAX_WRITE_BYTES,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Write a UTF-8 text file inside the workspace and return metadata."""
        self.require_write_allowed(path, approved=approved)
        if not isinstance(content, str):
            raise FileToolError("content must be a string")
        size = len(content.encode("utf-8"))
        if size > max_bytes:
            raise FileToolError(f"Content is too large to write ({size} bytes): {path}")
        resolved = self._resolve_writable_file(path, overwrite=overwrite)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._write_text_atomic(resolved, content, overwrite=overwrite)
        return {
            "path": self._relative(resolved),
            "bytes": size,
            "size_bytes": resolved.stat().st_size,
            "created": not overwrite,
        }

    def edit_file(
        self,
        path: str | Path,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        max_bytes: int = MAX_WRITE_BYTES,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Edit a file by replacing an exact string."""
        self.require_write_allowed(path, approved=approved)
        if not old_string:
            raise FileToolError("old_string must not be empty")
        resolved = self._resolve_text_file(path, max_bytes=max_bytes)
        content = resolved.read_text(encoding="utf-8")
        occurrences = content.count(old_string)
        if occurrences == 0:
            raise FileToolError(f"old_string was not found in {self._relative(resolved)}")
        if occurrences > 1 and not replace_all:
            raise FileToolError(
                f"old_string matched {occurrences} times in {self._relative(resolved)}; "
                "set replace_all=true or provide a more specific old_string"
            )
        replacement_count = occurrences if replace_all else 1
        new_content = content.replace(old_string, new_string, replacement_count)
        size = len(new_content.encode("utf-8"))
        if size > max_bytes:
            raise FileToolError(f"Edited content is too large to write ({size} bytes): {path}")
        self._write_text_atomic(resolved, new_content, overwrite=True)
        return {
            "path": self._relative(resolved),
            "replacements": replacement_count,
            "bytes": size,
            "size_bytes_before": len(content.encode("utf-8")),
            "size_bytes_after": size,
        }

    def delete_file(self, path: str | Path, *, approved: bool = False) -> dict[str, Any]:
        """Delete a file inside the workspace."""
        self.require_write_allowed(path, approved=approved)
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise FileToolError(f"Not a file: {path}")
        if self._is_excluded(resolved):
            raise FileToolError(f"Path is excluded: {path}")
        size = resolved.stat().st_size
        relative = self._relative(resolved)
        resolved.unlink()
        return {"path": relative, "deleted": True, "size_bytes": size}

    def make_directory(self, path: str | Path, *, approved: bool = False) -> str:
        """Create a directory inside the workspace."""
        self.require_write_allowed(path, approved=approved)
        resolved = self._resolve(path)
        if self._is_excluded(resolved):
            raise FileToolError(f"Path is excluded: {path}")
        if resolved.exists() and not resolved.is_dir():
            raise FileToolError(f"Path exists and is not a directory: {path}")
        resolved.mkdir(parents=True, exist_ok=True)
        return self._relative(resolved)

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.workspace):
            raise FileToolError(f"Path escapes workspace: {path}")
        return resolved

    def _resolve_text_file(self, path: str | Path, max_bytes: int) -> Path:
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise FileToolError(f"Not a file: {path}")
        if self._is_excluded(resolved):
            raise FileToolError(f"Path is excluded: {path}")
        size = resolved.stat().st_size
        if size > max_bytes:
            raise FileToolError(f"File is too large to read ({size} bytes): {path}")
        return resolved

    def _resolve_writable_file(self, path: str | Path, overwrite: bool) -> Path:
        resolved = self._resolve(path)
        if self._is_excluded(resolved):
            raise FileToolError(f"Path is excluded: {path}")
        if resolved.exists() and not resolved.is_file():
            raise FileToolError(f"Not a file: {path}")
        if resolved.exists() and not overwrite:
            raise FileToolError(f"File already exists: {path}")
        if self._is_excluded(resolved.parent):
            raise FileToolError(f"Parent path is excluded: {path}")
        return resolved

    def _relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.workspace))

    def _write_text_atomic(self, path: Path, content: str, overwrite: bool) -> None:
        """Write text via a same-directory temp file and atomic rename/link."""
        temp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        try:
            with temp_path.open("x", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            if overwrite:
                os.replace(temp_path, path)
                self._fsync_directory(path.parent)
            else:
                try:
                    os.link(temp_path, path)
                    self._fsync_directory(path.parent)
                except FileExistsError as e:
                    raise FileToolError(f"File already exists: {self._relative(path)}") from e
                finally:
                    temp_path.unlink(missing_ok=True)
        finally:
            temp_path.unlink(missing_ok=True)

    def _fsync_directory(self, path: Path) -> None:
        """Best-effort directory fsync so atomic renames are durable."""
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _is_excluded(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.workspace)
        except ValueError:
            return True
        parts = set(relative.parts)
        if parts & DEFAULT_EXCLUDES:
            return True
        return any(fnmatch.fnmatch(part, "*.egg-info") for part in relative.parts)

    def _normalize_limit(self, limit: int, max_limit: int) -> int:
        if limit < 1:
            raise FileToolError("limit must be >= 1")
        return min(limit, max_limit)

    def _compile_regex(self, query: str) -> Pattern[str]:
        try:
            return re.compile(query)
        except re.error as e:
            raise FileToolError(f"Invalid regular expression: {e}") from e

    def _match_column(self, line: str, query: str, compiled: Pattern[str] | None) -> int | None:
        if compiled is not None:
            match = compiled.search(line)
            return match.start() + 1 if match else None
        column = line.find(query)
        return column + 1 if column >= 0 else None
