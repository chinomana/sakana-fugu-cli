"""
Speech-to-Text engine using Faster-Whisper for local transcription.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fugu_vibe.config import Config

logger = structlog.get_logger()

# Optional faster-whisper
try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    WhisperModel = None  # type: ignore


class STTEngine:
    """
    Speech-to-Text engine with Faster-Whisper local inference.

    Models: tiny, base, small, medium, large-v3
    Default: base (good balance of speed/accuracy)

    Usage:
        stt = STTEngine(config)
        await stt.load()

        text = await stt.transcribe(audio_path)
        # or
        text = await stt.transcribe_bytes(audio_bytes)
    """

    def __init__(self, config: Config | None = None):
        self.config = config
        self.voice_config = config.voice if config else None

        self._model: WhisperModel | None = None
        self._model_size = "base"
        self._language = "auto"

        if self.voice_config:
            self._model_size = self.voice_config.model
            self._language = self.voice_config.language

    @property
    def is_available(self) -> bool:
        return HAS_WHISPER

    async def load(self) -> None:
        """Load the Whisper model."""
        if not HAS_WHISPER:
            raise RuntimeError(
                "faster-whisper not installed. "
                "Install with: pip install fugu-vibe-cli[voice]"
            )

        logger.info("loading_whisper_model", model=self._model_size)

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                self._model_size,
                device="cpu",  # Could be "cuda" if available
                compute_type="int8",
            )
        )

        logger.info("whisper_model_loaded", model=self._model_size)

    async def transcribe(self, audio_path: Path | str) -> str:
        """
        Transcribe audio file to text.

        Args:
            audio_path: Path to audio file (WAV, MP3, etc.)

        Returns:
            Transcribed text
        """
        if not self._model:
            await self.load()

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Run transcription in thread pool
        loop = asyncio.get_event_loop()

        try:
            segments, info = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(  # type: ignore
                    str(audio_path),
                    language=None if self._language == "auto" else self._language,
                    task="transcribe",
                    vad_filter=True,
                )
            )

            # Collect all segments
            texts = []
            for segment in segments:
                texts.append(segment.text.strip())

            result = " ".join(texts)

            logger.info(
                "transcription_complete",
                language=info.language if hasattr(info, "language") else "unknown",
                duration=info.duration if hasattr(info, "duration") else 0,
                text_length=len(result),
            )

            return result

        except Exception as e:
            logger.error("transcription_failed", error=str(e))
            raise

    async def transcribe_bytes(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio from bytes.

        Saves to temp file then transcribes.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        try:
            return await self.transcribe(temp_path)
        finally:
            await asyncio.to_thread(Path(temp_path).unlink, missing_ok=True)

    def unload(self) -> None:
        """Unload model to free memory."""
        self._model = None
        logger.info("whisper_model_unloaded")
