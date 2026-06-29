"""Workspace-safe file tools."""

from __future__ import annotations

import fnmatch
import os
import uuid
from dataclasses import dataclass
from pathlib import Path


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


class FileToolError(Exception):
    """Raised when a file tool request is invalid or unsafe."""


@dataclass
class FileTools:
    """File operations constrained to one workspace."""

    workspace: Path

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()

    def list_files(self, pattern: str = "**/*", limit: int = 200) -> list[str]:
        """List workspace files matching a glob pattern."""
        results: list[str] = []
        for path in sorted(self.workspace.glob(pattern)):
            if len(results) >= limit:
                break
            if not path.is_file() or self._is_excluded(path):
                continue
            results.append(self._relative(path))
        return results

    def read_file(
        self,
        path: str | Path,
        max_bytes: int = MAX_READ_BYTES,
        start_line: int = 1,
        limit: int | None = None,
    ) -> str:
        """Read a UTF-8 text file from the workspace."""
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise FileToolError(f"Not a file: {path}")
        if self._is_excluded(resolved):
            raise FileToolError(f"Path is excluded: {path}")
        size = resolved.stat().st_size
        if size > max_bytes:
            raise FileToolError(f"File is too large to read ({size} bytes): {path}")
        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise FileToolError(f"File is not UTF-8 text: {path}") from e
        if limit is None:
            return content
        if start_line < 1:
            raise FileToolError("start_line must be >= 1")
        limit = min(limit, MAX_READ_LINES)
        lines = content.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + limit]
        return "\n".join(selected) + ("\n" if selected else "")

    def search(
        self,
        query: str,
        pattern: str = "**/*",
        limit: int = 50,
        max_file_bytes: int = MAX_SEARCH_BYTES,
    ) -> list[dict[str, str | int]]:
        """Search UTF-8 workspace files for a literal query."""
        if not query:
            raise FileToolError("Search query must not be empty")

        matches: list[dict[str, str | int]] = []
        for path in sorted(self.workspace.glob(pattern)):
            if len(matches) >= limit:
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
                if query in line:
                    matches.append(
                        {
                            "path": self._relative(path),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
                    if len(matches) >= limit:
                        break
        return matches

    def write_file(
        self,
        path: str | Path,
        content: str,
        overwrite: bool = True,
        max_bytes: int = MAX_WRITE_BYTES,
    ) -> str:
        """Write a UTF-8 text file inside the workspace."""
        if not isinstance(content, str):
            raise FileToolError("content must be a string")
        size = len(content.encode("utf-8"))
        if size > max_bytes:
            raise FileToolError(f"Content is too large to write ({size} bytes): {path}")
        resolved = self._resolve(path)
        if self._is_excluded(resolved):
            raise FileToolError(f"Path is excluded: {path}")
        if resolved.exists() and not resolved.is_file():
            raise FileToolError(f"Not a file: {path}")
        if resolved.exists() and not overwrite:
            raise FileToolError(f"File already exists: {path}")
        if self._is_excluded(resolved.parent):
            raise FileToolError(f"Parent path is excluded: {path}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._write_text_atomic(resolved, content, overwrite=overwrite)
        return self._relative(resolved)

    def make_directory(self, path: str | Path) -> str:
        """Create a directory inside the workspace."""
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
                # Atomic create-if-absent: link fails if the target exists.
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
