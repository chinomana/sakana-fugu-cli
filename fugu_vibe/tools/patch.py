"""Workspace-safe patch application utilities."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_PATCH_BYTES = 1024 * 1024


class PatchToolError(Exception):
    """Raised when a patch is invalid or unsafe."""


@dataclass
class PatchResult:
    """Result of a patch operation."""

    applied: bool
    stdout: str
    stderr: str


@dataclass
class PatchTool:
    """Apply unified diffs inside a workspace."""

    workspace: Path

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()

    def git_diff(self) -> str:
        result = subprocess.run(
            ["git", "diff", "--"],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise PatchToolError(result.stderr.strip() or "git diff failed")
        return result.stdout

    def read_patch_file(self, path: str | Path) -> str:
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise PatchToolError(f"Not a file: {path}")
        size = resolved.stat().st_size
        if size > MAX_PATCH_BYTES:
            raise PatchToolError(f"Patch is too large ({size} bytes): {path}")
        try:
            patch_text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise PatchToolError(f"Patch is not UTF-8 text: {path}") from e
        self.validate_patch_text(patch_text)
        return patch_text

    def check(self, patch_text: str) -> PatchResult:
        self.validate_patch_text(patch_text)
        return self._git_apply(patch_text, check=True)

    def apply(self, patch_text: str) -> PatchResult:
        self.validate_patch_text(patch_text)
        return self._git_apply(patch_text, check=False)

    def validate_patch_text(self, patch_text: str) -> None:
        if not patch_text.strip():
            raise PatchToolError("Patch is empty")
        if len(patch_text.encode("utf-8")) > MAX_PATCH_BYTES:
            raise PatchToolError("Patch is too large")
        for line in patch_text.splitlines():
            if line.startswith(("--- ", "+++ ", "diff --git ")):
                self._validate_patch_line(line)

    def _validate_patch_line(self, line: str) -> None:
        parts = line.split()
        candidates = parts[1:] if line.startswith("diff --git ") else parts[1:2]
        for raw_path in candidates:
            if raw_path == "/dev/null":
                continue
            path = raw_path
            if path.startswith(("a/", "b/")):
                path = path[2:]
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise PatchToolError(f"Unsafe patch path: {raw_path}")

    def _git_apply(self, patch_text: str, check: bool) -> PatchResult:
        args = ["git", "apply"]
        if check:
            args.append("--check")
        result = subprocess.run(
            args,
            cwd=self.workspace,
            input=patch_text,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise PatchToolError(result.stderr.strip() or "git apply failed")
        return PatchResult(applied=not check, stdout=result.stdout, stderr=result.stderr)

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.workspace):
            raise PatchToolError(f"Path escapes workspace: {path}")
        return resolved
