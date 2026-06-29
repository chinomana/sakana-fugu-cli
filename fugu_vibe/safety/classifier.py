"""Simplified safety policy for local command and file operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class SafetyMode(StrEnum):
    """User-selected automation level."""

    ASK = "ask"
    AUTO_SAFE = "auto-safe"
    AUTO_EDIT = "auto-edit"
    AUTO = "auto"


class CommandRisk(StrEnum):
    """Coarse command safety classification."""

    SAFE = "safe"
    ASK = "ask"
    UNSAFE = "unsafe"


@dataclass(frozen=True)
class SafetyDecision:
    """Policy decision for an operation."""

    allowed: bool
    requires_approval: bool
    risk: CommandRisk | None
    reason: str


UNSAFE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\brm\s+(-[\w-]*r[\w-]*f|-\\?rf|-[\w-]*f[\w-]*r)\b",
        r"\bsudo\b",
        r"\bchmod\s+(?:-R\s+)?777\b",
        r"\bchown\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+checkout\s+--\b",
        r"\bcurl\b.+\|\s*(?:sh|bash)\b",
        r"\bwget\b.+\|\s*(?:sh|bash)\b",
        r"\b(?:sh|bash)\s*<\s*\(",
        r">\s*/dev/(?:sd|disk|nvme)",
        r"\bmkfs\b",
        r"\bdd\s+.*\bof=/dev/",
    )
)

SAFE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^pwd$",
        r"^ls(?:\s|$)",
        r"^cat\s+[^;&|]+$",
        r"^grep\s+",
        r"^rg(?:\s|$)",
        r"^find\s+",
        r"^git\s+status(?:\s|$)",
        r"^git\s+diff(?:\s|$)",
        r"^git\s+log(?:\s|$)",
        r"^git\s+show(?:\s|$)",
        r"^python\s+-m\s+pytest(?:\s|$)",
        r"^pytest(?:\s|$)",
        r"^ruff\s+check(?:\s|$)",
        r"^mypy(?:\s|$)",
        r"^npm\s+test(?:\s|$)",
        r"^pnpm\s+test(?:\s|$)",
        r"^yarn\s+test(?:\s|$)",
        r"^cargo\s+test(?:\s|$)",
    )
)

SENSITIVE_FILE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:^|/)\.env(?:\.|$)",
        r"(?:^|/)\.npmrc$",
        r"(?:^|/)\.pypirc$",
        r"(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519)$",
        r"(?:^|/)\.ssh/",
    )
)


def is_sensitive_path(path: str | None) -> bool:
    """Return whether a path should always require explicit approval."""
    if not path:
        return False
    normalized = path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in SENSITIVE_FILE_PATTERNS)


def normalize_mode(mode: str | SafetyMode) -> SafetyMode:
    """Normalize legacy and configured safety modes."""
    if isinstance(mode, SafetyMode):
        return mode
    value = (mode or "ask").strip().lower()
    if value == "off":
        return SafetyMode.ASK
    try:
        return SafetyMode(value)
    except ValueError:
        return SafetyMode.ASK


def classify_command(command: str) -> CommandRisk:
    """Classify a shell command with conservative regex heuristics."""
    normalized = " ".join(command.strip().split())
    if not normalized:
        return CommandRisk.UNSAFE
    if any(pattern.search(normalized) for pattern in UNSAFE_PATTERNS):
        return CommandRisk.UNSAFE
    if any(pattern.search(normalized) for pattern in SAFE_PATTERNS):
        return CommandRisk.SAFE
    return CommandRisk.ASK


@dataclass(frozen=True)
class SafetyPolicy:
    """Evaluate local operations under a configured safety mode."""

    mode: SafetyMode | str = SafetyMode.ASK

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", normalize_mode(self.mode))

    def evaluate_command(self, command: str, *, approved: bool = False) -> SafetyDecision:
        risk = classify_command(command)
        if risk == CommandRisk.UNSAFE:
            return SafetyDecision(False, False, risk, "Command blocked as unsafe")
        if self.mode == SafetyMode.AUTO:
            return SafetyDecision(True, False, risk, "Command allowed by auto mode")
        if self.mode in {SafetyMode.AUTO_SAFE, SafetyMode.AUTO_EDIT} and risk == CommandRisk.SAFE:
            return SafetyDecision(True, False, risk, f"Safe command allowed by {self.mode.value} mode")
        if approved:
            return SafetyDecision(True, False, risk, "Command approved by user")
        return SafetyDecision(False, True, risk, "Command requires approval")

    def evaluate_file_write(self, path: str | None = None, *, approved: bool = False) -> SafetyDecision:
        if approved:
            return SafetyDecision(True, False, None, "File write approved by user")
        if is_sensitive_path(path):
            return SafetyDecision(False, True, None, f"File write requires approval for sensitive path: {path}")
        if self.mode in {SafetyMode.AUTO_EDIT, SafetyMode.AUTO}:
            return SafetyDecision(True, False, None, f"File write allowed by {self.mode.value} mode")
        return SafetyDecision(False, True, None, "File write requires approval")
