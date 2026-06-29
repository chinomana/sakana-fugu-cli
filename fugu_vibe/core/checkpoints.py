"""Workspace checkpoints for safe rollback."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class CheckpointError(Exception):
    """Raised when checkpoint operations fail."""


@dataclass
class Checkpoint:
    """A saved rollback point."""

    id: str
    created_at: str
    message: str
    base_revision: str | None
    patch_path: Path
    changed_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "message": self.message,
            "base_revision": self.base_revision,
            "patch_path": str(self.patch_path),
            "changed_files": self.changed_files,
        }


class CheckpointManager:
    """Create, list, and restore git patch checkpoints."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.root = self.workspace / ".fugu-vibe" / "checkpoints"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "manifest.json"

    def create(self, message: str = "manual checkpoint") -> Checkpoint:
        """Save the current workspace diff as a rollback checkpoint."""
        self._ensure_git_repo()
        patch_parts = [
            self._git("diff", "--binary"),
            self._git("diff", "--binary", "--cached"),
            self._untracked_patch(),
        ]
        combined_patch = "\n".join(part for part in patch_parts if part.strip())
        if not combined_patch.strip():
            raise CheckpointError("No git diff to checkpoint")

        checkpoint_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
        patch_path = self.root / f"{checkpoint_id}.patch"
        patch_path.write_text(combined_patch, encoding="utf-8")
        checkpoint = Checkpoint(
            id=checkpoint_id,
            created_at=datetime.now().isoformat(),
            message=message,
            base_revision=self._git("rev-parse", "--short", "HEAD").strip() or None,
            patch_path=patch_path,
            changed_files=self._changed_files(),
        )
        manifest = self._load_manifest()
        manifest.append(checkpoint.to_dict())
        self._write_manifest(manifest)
        return checkpoint

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        """List checkpoints newest first."""
        return list(reversed(self._load_manifest()))[:limit]

    def undo(self, checkpoint_id: str | None = None) -> dict[str, Any]:
        """Reverse-apply a checkpoint patch."""
        manifest = self._load_manifest()
        if not manifest:
            raise CheckpointError("No checkpoints available")
        selected = self._select_checkpoint(manifest, checkpoint_id)
        patch_path = Path(str(selected["patch_path"]))
        if not patch_path.exists():
            raise CheckpointError(f"Checkpoint patch missing: {patch_path}")
        self._run_git_stdin(["apply", "--reverse"], patch_path.read_text(encoding="utf-8"))
        remaining = [entry for entry in manifest if entry.get("id") != selected.get("id")]
        self._write_manifest(remaining)
        return {"undone": selected.get("id"), "message": selected.get("message"), "changed_files": selected.get("changed_files", [])}

    def _ensure_git_repo(self) -> None:
        try:
            self._git("rev-parse", "--is-inside-work-tree")
        except CheckpointError as e:
            raise CheckpointError("Checkpoints require a git repository") from e

    def _changed_files(self) -> list[str]:
        output = self._git("status", "--short")
        files: list[str] = []
        for line in output.splitlines():
            if len(line) > 3:
                files.append(line[3:])
        return files

    def _untracked_patch(self) -> str:
        files = [line for line in self._git("ls-files", "--others", "--exclude-standard").splitlines() if line]
        patches: list[str] = []
        for file_path in files:
            path = self.workspace / file_path
            if path.is_file():
                patches.append(self._git("diff", "--binary", "--no-index", "/dev/null", file_path, allow_error_code=1))
        return "\n".join(patches)

    def _select_checkpoint(self, manifest: list[dict[str, Any]], checkpoint_id: str | None) -> dict[str, Any]:
        if checkpoint_id is None:
            return manifest[-1]
        for entry in manifest:
            if entry.get("id") == checkpoint_id:
                return entry
        raise CheckpointError(f"Unknown checkpoint: {checkpoint_id}")

    def _load_manifest(self) -> list[dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _write_manifest(self, data: list[dict[str, Any]]) -> None:
        tmp_path = self.manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.manifest_path)

    def _git(self, *args: str, allow_error_code: int | None = None) -> str:
        process = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0 and process.returncode != allow_error_code:
            raise CheckpointError(process.stderr.strip() or process.stdout.strip() or f"git {' '.join(args)} failed")
        return process.stdout

    def _run_git_stdin(self, args: list[str], stdin: str) -> None:
        process = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise CheckpointError(process.stderr.strip() or process.stdout.strip() or f"git {' '.join(args)} failed")
