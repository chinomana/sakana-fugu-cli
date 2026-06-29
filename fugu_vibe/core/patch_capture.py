"""Capture model-proposed unified diffs for explicit user approval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DIFF_FENCE_RE = re.compile(r"```(?:diff|patch)\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


@dataclass
class CapturedPatch:
    """A saved model-proposed patch."""

    path: Path
    latest_path: Path
    check_error: str = ""


def capture_unified_diff(text: str, workspace: Path | None = None) -> CapturedPatch | None:
    """Save the first unified diff in text under .fugu-vibe/patches."""
    patch_text = _extract_unified_diff(text)
    if not patch_text:
        return None

    root = workspace or Path.cwd()
    patch_dir = root / ".fugu-vibe" / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = patch_dir / f"{timestamp}.patch"
    latest_path = patch_dir / "latest.patch"
    patch_text = patch_text.rstrip() + "\n"
    path.write_text(patch_text, encoding="utf-8")
    latest_path.write_text(patch_text, encoding="utf-8")
    return CapturedPatch(path=path, latest_path=latest_path)


def _extract_unified_diff(text: str) -> str | None:
    for match in DIFF_FENCE_RE.finditer(text):
        candidate = match.group(1).strip()
        if _looks_like_unified_diff(candidate):
            return candidate

    stripped = text.strip()
    if _looks_like_unified_diff(stripped):
        return stripped
    return None


def _looks_like_unified_diff(text: str) -> bool:
    lines = text.splitlines()
    has_header = any(line.startswith("diff --git ") for line in lines) or (
        any(line.startswith("--- ") for line in lines)
        and any(line.startswith("+++ ") for line in lines)
    )
    has_hunk = any(line.startswith("@@") for line in lines)
    return has_header and has_hunk
