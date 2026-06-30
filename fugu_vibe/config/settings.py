"""Configuration management with hierarchical loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog
import toml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


@dataclass(frozen=True)
class LoadedConfig:
    """Configuration plus the file path it was loaded from."""

    config: Config
    path: Path | None


class APIConfig(BaseSettings):
    """API connection settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_API_")

    base_url: str = "https://api.sakana.ai/v1"
    api_key: str = Field(default="", description="Sakana API key")
    timeout: int = 7200  # 2 hours for Fugu Ultra orchestration
    max_retries: int = 5
    stream: bool = True
    stream_idle_timeout_ms: int = 7_200_000  # 2h Sakana recommendation
    stream_max_retries: int = 5
    request_max_retries: int = 4


class ModelConfig(BaseSettings):
    """Model behavior settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_MODEL_")

    default: str = "fugu-ultra"  # fugu | fugu-ultra
    reasoning_effort: Literal["high", "xhigh", "max"] = "xhigh"
    adaptive_effort: bool = True
    max_output_tokens: int = 32768
    truncation: Literal["auto", "disabled"] = "auto"

    @field_validator("reasoning_effort")
    @classmethod
    def normalize_effort(cls, v: str) -> str:
        """Normalize 'max' to 'xhigh' (alias)."""
        return "xhigh" if v == "max" else v


class OrchestrationConfig(BaseSettings):
    """Orchestration visualization settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_ORCH_")

    viz_mode: Literal["full", "compact", "none"] = "full"
    show_token_usage: bool = True
    show_routing_decisions: bool = True
    infer_workers: bool = True
    heartbeat_interval: int = 30  # seconds
    initial_routing_threshold: float = 5.0  # seconds to infer routing
    worker_pattern_window: int = 10  # tokens to analyze patterns
    token_budget: int = 1_000_000
    token_budget_warning_ratio: float = 0.8
    max_orchestration_ratio: float = 0.5
    cost_per_million_tokens: float = 0.0


class VoiceConfig(BaseSettings):
    """Voice input settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_VOICE_")

    enabled: bool = False
    engine: Literal["faster-whisper", "whisper-api"] = "faster-whisper"
    model: str = "base"  # tiny, base, small, medium, large-v3
    language: str = "auto"
    push_to_talk_key: str = "space"
    vad_aggressiveness: int = 3  # 0-3
    auto_submit: bool = True
    silence_timeout: float = 2.0  # seconds of silence to stop recording
    min_recording_duration: float = 0.5  # minimum seconds to process


class TaskConfig(BaseSettings):
    """Async task management settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_TASK_")

    max_parallel: int = 5
    use_git_worktree: bool = True
    auto_merge: bool = True
    timeout: int = 1800  # 30 min per task
    git_default_branch: str = "main"
    worktree_prefix: str = "fugu-wt"


class PromptConfig(BaseSettings):
    """Prompt behavior settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_PROMPT_")

    unlimited_mode: bool = False  # Override base_instructions restrictions
    custom_instructions: str | None = None
    use_instruction_templates: bool = True
    preserve_full_history: bool = True  # Send full history (no previous_response_id)


class ToolConfig(BaseSettings):
    """Local tool execution policy."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_TOOLS_")

    terminal_enabled: bool = True
    terminal_approval: Literal["off", "ask", "auto-safe"] = "auto-safe"
    terminal_timeout_seconds: int = 120
    max_output_chars: int = 20_000
    max_tool_rounds: int = 10
    auto_test_after_edit: bool = True
    auto_test_command: str = "python -m pytest -q"
    auto_compile_after_edit: bool = True
    auto_lint_after_edit: bool = True
    auto_lint_command: str = "python -m ruff check ."


class MCPConfig(BaseSettings):
    """Model Context Protocol integration settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_MCP_")

    enabled: bool = True
    timeout_seconds: float = 30.0


class SafetyConfig(BaseSettings):
    """Safety governance and rollback settings."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_SAFETY_")

    mode: Literal["ask", "auto-safe", "auto-edit", "auto"] = "auto-safe"
    checkpoint_enabled: bool = True
    checkpoint_each_turn: bool = False


class PatchConfig(BaseSettings):
    """Patch application policy."""

    model_config = SettingsConfigDict(env_prefix="FUGU_VIBE_PATCH_")

    mode: Literal["propose-only", "ask-apply", "auto-apply-safe"] = "ask-apply"


class Config(BaseSettings):
    """Root configuration for Fugu Vibe CLI."""

    model_config = SettingsConfigDict(
        env_prefix="FUGU_VIBE_",
        env_nested_delimiter="__",
    )

    api: APIConfig = Field(default_factory=APIConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    tasks: TaskConfig = Field(default_factory=TaskConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    patch: PatchConfig = Field(default_factory=PatchConfig)

    @classmethod
    def from_file(cls, path: Path) -> Config:
        """Load configuration from TOML file."""
        if not path.exists():
            return cls()
        try:
            data = toml.load(path)
            return cls(**data)
        except Exception as e:
            logger.warning("config_load_failed", path=str(path), error=str(e))
            return cls()

    def to_file(self, path: Path) -> None:
        """Save configuration to TOML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            toml.dump(self.model_dump(), f)


def find_config_file() -> Path | None:
    """Find configuration file in standard locations."""
    # Priority: project > user > None
    search_paths = [
        Path.cwd() / ".fugu-vibe.toml",
        Path.home() / ".config" / "fugu-vibe" / "config.toml",
    ]
    for p in search_paths:
        if p.exists():
            return p
    return None


def load_config_with_source(override_path: Path | None = None) -> LoadedConfig:
    """Load configuration with hierarchy: defaults < file < env < CLI."""
    # Start with defaults
    config = Config()

    # Override from file
    config_path = override_path or find_config_file()
    if config_path:
        file_config = Config.from_file(config_path)
        # Re-validate merged values so nested config remains typed models.
        config = Config.model_validate(file_config.model_dump())
        logger.info("config_loaded_from_file", path=str(config_path))

    # Environment variables override (handled by pydantic-settings)
    # CLI flags will override via model_copy in CLI layer

    return LoadedConfig(config=config, path=config_path)


def load_config(override_path: Path | None = None) -> Config:
    """Load configuration with hierarchy: defaults < file < env < CLI."""
    return load_config_with_source(override_path).config
