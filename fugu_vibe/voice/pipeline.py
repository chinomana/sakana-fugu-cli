"""
Voice pipeline: recorder → STT → command parser → task submission.

Provides continuous voice interaction mode for hands-free vibe coding.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog

from fugu_vibe.core.event_bus import EventBus, EventType
from fugu_vibe.voice.recorder import AudioConfig, AudioRecorder
from fugu_vibe.voice.stt import STTEngine

if TYPE_CHECKING:
    from fugu_vibe.config import Config
    from fugu_vibe.core.task_manager import TaskManager

logger = structlog.get_logger()


class VoicePipeline:
    """
    End-to-end voice pipeline for async task submission.

    Flow:
    1. User presses push-to-talk key (default: Space)
    2. AudioRecorder captures with VAD auto-segmentation
    3. STTEngine transcribes with Faster-Whisper
    4. CommandParser extracts task intent
    5. TaskManager submits the task

    Usage:
        pipeline = VoicePipeline(config, task_manager, event_bus)
        await pipeline.start()  # Start listening

        # User presses space, speaks, releases
        # Task is automatically submitted

        await pipeline.stop()
    """

    def __init__(
        self,
        config: Config,
        task_manager: TaskManager,
        event_bus: EventBus,
    ):
        self.config = config
        self.task_manager = task_manager
        self.event_bus = event_bus
        self.voice_config = config.voice

        # Components
        self.recorder = AudioRecorder(AudioConfig())
        self.stt = STTEngine(config)

        # State
        self._running = False
        self._listen_task: asyncio.Task | None = None
        self._is_recording = False

    @property
    def is_available(self) -> bool:
        return self.recorder.is_available and self.stt.is_available

    async def start(self) -> None:
        """Start the voice pipeline in background listening mode."""
        if not self.is_available:
            raise RuntimeError(
                "Voice not available. Install with: pip install fugu-vibe-cli[voice]"
            )

        self._running = True

        # Load STT model
        await self.stt.load()

        # Start listening loop
        self._listen_task = asyncio.create_task(self._listen_loop())

        await self.event_bus.emit(
            EventType.VOICE_RECORDING,
            {"status": "ready", "trigger_key": self.voice_config.push_to_talk_key},
        )

        logger.info("voice_pipeline_started")

    async def stop(self) -> None:
        """Stop the voice pipeline."""
        self._running = False

        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task

        self.recorder.close()
        self.stt.unload()

        logger.info("voice_pipeline_stopped")

    async def record_and_submit(self) -> None:
        """
        Single-shot: record audio and submit as task.
        Used when push-to-talk key is pressed.
        """
        if self._is_recording:
            return

        self._is_recording = True

        try:
            # Notify start
            await self.event_bus.emit(
                EventType.VOICE_RECORDING,
                {"status": "recording"},
            )

            # Record audio
            audio_path = await self.recorder.record(
                silence_timeout=self.voice_config.silence_timeout,
                min_duration=self.voice_config.min_recording_duration,
            )

            if not audio_path:
                await self.event_bus.emit(
                    EventType.VOICE_ERROR,
                    {"error": "No audio recorded or too short"},
                )
                return

            # Transcribe
            await self.event_bus.emit(
                EventType.VOICE_TRANSCRIBED,
                {"status": "transcribing"},
            )

            text = await self.stt.transcribe(audio_path)

            await self.event_bus.emit(
                EventType.VOICE_TRANSCRIBED,
                {"text": text, "status": "done"},
            )

            # Parse and submit
            task_name, prompt, options = self._parse_command(text)

            await self.event_bus.emit(
                EventType.VOICE_COMMAND,
                {"text": text, "task_name": task_name, "parsed": True},
            )

            task = await self.task_manager.submit(
                name=task_name,
                prompt=prompt,
                **options,
            )

            logger.info(
                "voice_task_submitted",
                task_id=task.task_id,
                name=task_name,
                prompt_preview=text[:100],
            )

        except Exception as e:
            await self.event_bus.emit(
                EventType.VOICE_ERROR,
                {"error": str(e)},
            )
            logger.error("voice_submission_failed", error=str(e))
        finally:
            self._is_recording = False
            await self.event_bus.emit(
                EventType.VOICE_RECORDING,
                {"status": "ready"},
            )

    async def _listen_loop(self) -> None:
        """
        Background loop listening for voice commands.

        In a full implementation, this would use a keyboard hook
        library (e.g., pynput) to detect the push-to-talk key.
        For now, it's a placeholder that can be triggered manually.
        """
        logger.info("voice_listen_loop_started")

        while self._running:
            try:
                # Placeholder: in real implementation, this would
                # wait for keyboard events (push-to-talk)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    def _parse_command(self, text: str) -> tuple[str, str, dict]:
        """
        Parse natural language into task parameters.

        Simple rule-based parser:
        - First sentence = task name
        - Full text = prompt
        - Keywords trigger options:
          - "search/web" → web_search=True
          - "deep/thorough" → effort="xhigh"
          - "quick/fast" → effort="high"

        Returns:
            (task_name, prompt, options_dict)
        """
        text = text.strip()

        # Extract task name (first sentence or first 5 words)
        sentences = text.split(".")
        task_name = sentences[0][:50] if sentences else "Voice Task"

        # Default options
        options: dict = {
            "model": self.config.model.default,
            "effort": self.config.model.reasoning_effort,
            "web_search": False,
        }

        lower = text.lower()

        # Detect web search intent
        if any(kw in lower for kw in ["search", "look up", "find online", "web"]):
            options["web_search"] = True

        # Detect effort level
        if any(kw in lower for kw in ["quick", "fast", "simple", "brief"]):
            options["effort"] = "high"
        elif any(kw in lower for kw in ["deep", "thorough", "careful", "detailed"]):
            options["effort"] = "xhigh"

        return task_name, text, options
