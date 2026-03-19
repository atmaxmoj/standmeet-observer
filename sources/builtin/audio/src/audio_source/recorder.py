"""Continuous audio recording → WAV chunks using sounddevice."""

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import sounddevice as sd
import soundfile as sf

from audio_source.config import CHANNELS, CHUNK_DURATION_SECONDS, CHUNKS_DIR, SAMPLE_RATE

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio in fixed-duration WAV chunks from a specified device."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        chunk_seconds: int = CHUNK_DURATION_SECONDS,
        output_dir: str = CHUNKS_DIR,
        device: int | str | None = None,
        source: str = "mic",
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_seconds = chunk_seconds
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.device = device
        self.source = source

        self._stop_event = threading.Event()
        self._current_file: sf.SoundFile | None = None
        self._chunk_start: datetime | None = None
        self._frames_written = 0
        self._chunk_path: str | None = None

        logger.debug(
            "recorder init: source=%s device=%s rate=%d channels=%d chunk=%ds dir=%s",
            source, device, sample_rate, channels, chunk_seconds, output_dir,
        )

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each block of audio data."""
        if status:
            logger.warning("audio callback status: %s", status)

        if self._current_file is not None and not self._current_file.closed:
            self._current_file.write(indata.copy())
            self._frames_written += frames

    def _start_new_chunk(self) -> str:
        """Close current chunk and start a new WAV file. Returns path of completed chunk or empty string."""
        completed_path = ""

        # Close previous chunk
        if self._current_file is not None and not self._current_file.closed:
            self._current_file.close()
            completed_path = self._chunk_path
            duration = self._frames_written / self.sample_rate
            logger.info(
                "chunk completed: %s (%.1fs, %d frames)",
                completed_path, duration, self._frames_written,
            )

        # Start new chunk
        self._chunk_start = datetime.now(timezone.utc)
        ts = self._chunk_start.strftime("%Y%m%d_%H%M%S")
        self._chunk_path = str(self.output_dir / f"chunk_{self.source}_{ts}.wav")
        self._frames_written = 0

        self._current_file = sf.SoundFile(
            self._chunk_path,
            mode="w",
            samplerate=self.sample_rate,
            channels=self.channels,
            format="WAV",
            subtype="PCM_16",
        )
        logger.debug("started new chunk: %s", self._chunk_path)

        return completed_path

    def record(self, on_chunk_ready):
        """
        Main recording loop. Blocks until stop() is called.
        Calls on_chunk_ready(chunk_path, start_timestamp, duration_seconds)
        for each completed chunk.
        """
        logger.info(
            "starting recording: rate=%d channels=%d chunk=%ds",
            self.sample_rate, self.channels, self.chunk_seconds,
        )

        # List available devices for debugging
        devices = sd.query_devices()
        default_input = sd.query_devices(kind="input")
        logger.debug("default input device: %s", default_input["name"])
        logger.debug("available input devices: %d total", len(devices))
        if self.device is not None:
            logger.info("using device: %s (source=%s)", self.device, self.source)

        self._start_new_chunk()

        try:
            with sd.InputStream(
                device=self.device,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                callback=self._audio_callback,
            ):
                logger.info("audio stream opened, recording...")

                while not self._stop_event.is_set():
                    time.sleep(1)

                    # Check if chunk duration exceeded
                    elapsed = self._frames_written / self.sample_rate
                    if elapsed >= self.chunk_seconds:
                        chunk_start_ts = self._chunk_start.isoformat()
                        completed = self._start_new_chunk()
                        if completed:
                            on_chunk_ready(completed, chunk_start_ts, elapsed)

        except Exception:
            logger.exception("recording error")
        finally:
            # Close final chunk
            if self._current_file is not None and not self._current_file.closed:
                self._current_file.close()
                if self._frames_written > 0:
                    duration = self._frames_written / self.sample_rate
                    logger.info(
                        "final chunk: %s (%.1fs)",
                        self._chunk_path, duration,
                    )
                    on_chunk_ready(
                        self._chunk_path,
                        self._chunk_start.isoformat(),
                        duration,
                    )

    def stop(self):
        """Signal the recording loop to stop."""
        logger.info("stop requested")
        self._stop_event.set()
