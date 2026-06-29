"""
Audio recorder with Voice Activity Detection (VAD) for
push-to-talk voice input.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Optional imports - handle gracefully if not installed
try:
    import pyaudio
    import webrtcvad
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False
    pyaudio = None  # type: ignore
    webrtcvad = None  # type: ignore


@dataclass
class AudioConfig:
    """Audio recording configuration."""

    sample_rate: int = 16000  # 16kHz required by Whisper
    chunk_duration_ms: int = 30  # VAD chunk size
    channels: int = 1  # Mono
    format: int = 16  # 16-bit PCM


class AudioRecorder:
    """
    Push-to-talk audio recorder with VAD-based auto-segmentation.

    Usage:
        recorder = AudioRecorder(config)

        # Start recording (blocks until silence timeout)
        audio_path = await recorder.record()

        # Or manual control
        recorder.start_recording()
        await asyncio.sleep(5)
        audio_path = recorder.stop_recording()
    """

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()
        self._vad: Any = None
        self._audio: Any = None
        self._stream: Any = None

        self._recording = False
        self._frames: list[bytes] = []
        self._silence_start: float | None = None

        if HAS_AUDIO:
            try:
                self._vad = webrtcvad.Vad(3)  # Aggressiveness 0-3
                self._audio = pyaudio.PyAudio()
            except Exception as e:
                logger.warning("audio_init_failed", error=str(e))
        else:
            logger.warning("audio_deps_not_installed",
                         install="pip install fugu-vibe-cli[voice]")

    @property
    def is_available(self) -> bool:
        return HAS_AUDIO and self._audio is not None

    async def record(
        self,
        silence_timeout: float = 2.0,
        max_duration: float = 60.0,
        min_duration: float = 0.5,
    ) -> Path | None:
        """
        Record audio until silence is detected or max duration reached.

        Args:
            silence_timeout: Seconds of silence to stop recording
            max_duration: Maximum recording duration
            min_duration: Minimum duration to save

        Returns:
            Path to saved audio file, or None if recording failed/too short
        """
        if not self.is_available:
            logger.error("audio_recording_not_available")
            return None

        self._recording = True
        self._frames = []
        self._silence_start = None

        try:
            # Open audio stream
            chunk_size = int(
                self.config.sample_rate * self.config.chunk_duration_ms / 1000
            )
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=chunk_size,
            )

            logger.info("recording_started", max_duration=max_duration)
            start_time = time.monotonic()

            while self._recording:
                # Read audio chunk
                try:
                    frame = self._stream.read(chunk_size, exception_on_overflow=False)
                except Exception as e:
                    logger.error("audio_read_error", error=str(e))
                    break

                self._frames.append(frame)

                # VAD check
                is_speech = self._vad.is_speech(frame, self.config.sample_rate)

                if not is_speech:
                    if self._silence_start is None:
                        self._silence_start = time.monotonic()
                    elif time.monotonic() - self._silence_start > silence_timeout:
                        logger.info("silence_detected",
                                  duration=time.monotonic() - self._silence_start)
                        break
                else:
                    self._silence_start = None

                # Max duration check
                elapsed = time.monotonic() - start_time
                if elapsed > max_duration:
                    logger.info("max_duration_reached", duration=elapsed)
                    break

                await asyncio.sleep(0)  # Yield control

            # Calculate duration
            duration = time.monotonic() - start_time

            if duration < min_duration:
                logger.warning("recording_too_short", duration=duration)
                return None

            # Save to file
            return self._save_audio()

        finally:
            self._cleanup()

    def start_recording(self) -> None:
        """Start recording (manual mode)."""
        self._recording = True
        self._frames = []

        if self.is_available:
            chunk_size = int(
                self.config.sample_rate * self.config.chunk_duration_ms / 1000
            )
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=chunk_size,
            )

    def stop_recording(self) -> Path | None:
        """Stop recording and save (manual mode)."""
        self._recording = False
        try:
            return self._save_audio()
        finally:
            self._cleanup()

    def _save_audio(self) -> Path | None:
        """Save recorded frames to WAV file."""
        if not self._frames:
            return None

        try:
            import wave

            # Create temp file
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="fugu-voice-")

            with wave.open(path, "wb") as wf:
                wf.setnchannels(self.config.channels)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(self.config.sample_rate)
                wf.writeframes(b"".join(self._frames))

            logger.info("audio_saved", path=path,
                       duration=len(self._frames) * self.config.chunk_duration_ms / 1000)
            return Path(path)

        except Exception as e:
            logger.error("audio_save_failed", error=str(e))
            return None

    def _cleanup(self) -> None:
        """Clean up audio resources."""
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def close(self) -> None:
        """Release audio resources."""
        self._cleanup()
        if self._audio:
            self._audio.terminate()
