"""Audio source plugin — microphone capture + transcription via Faster Whisper.

Unlike poll-based sources (zsh, chrome, etc.), audio uses a fundamentally
different pattern: background recording threads produce WAV chunks via
callbacks, which are then transcribed and ingested.  This requires a
custom start() override instead of the default collect()-in-a-loop.
"""

import logging
import os
import threading
import time

from source_framework.plugin import SourcePlugin, ProbeResult

logger = logging.getLogger(__name__)


class AudioSource(SourcePlugin):
    """Captures microphone audio, transcribes with Faster Whisper, and pushes text records.

    The heavy lifting (recording + transcription) lives in the ``audio`` package
    (audio/src/audio/). This plugin wires it into the source-framework lifecycle.
    Phase 2 will migrate that code directly into this plugin.
    """

    def probe(self) -> ProbeResult:
        """Check for sounddevice availability and at least one input device."""
        warnings: list[str] = []

        try:
            import sounddevice as sd  # noqa: F401
        except ImportError:
            return ProbeResult(
                available=False,
                source="audio",
                description="sounddevice not installed",
                warnings=["pip install sounddevice"],
            )
        except OSError as exc:
            return ProbeResult(
                available=False,
                source="audio",
                description=f"PortAudio unavailable: {exc}",
                warnings=["install PortAudio (brew install portaudio / apt install libportaudio2)"],
            )

        try:
            raw = sd.query_devices()
            # query_devices returns DeviceList — iterate and check each device
            input_devices = []
            for d in raw:
                try:
                    if d["max_input_channels"] > 0:
                        input_devices.append(d)
                except (KeyError, TypeError):
                    pass
        except Exception as exc:
            return ProbeResult(
                available=False,
                source="audio",
                description=f"failed to query audio devices: {exc}",
            )

        if not input_devices:
            return ProbeResult(
                available=False,
                source="audio",
                description="no input devices found",
                warnings=["connect a microphone or enable built-in mic"],
            )

        names = [d["name"] for d in input_devices[:3]]
        if len(input_devices) > 3:
            names.append(f"... +{len(input_devices) - 3} more")

        return ProbeResult(
            available=True,
            source="audio",
            description=f"found {len(input_devices)} input device(s)",
            paths=names,
            warnings=warnings,
        )

    def collect(self) -> list[dict]:
        """Stub — audio uses a custom start() loop, not poll-based collect()."""
        return []

    def start(self, client, config: dict):
        """Custom start: record in background threads → transcribe chunks → ingest.

        Mirrors the logic in audio/src/audio/daemon.py but adapted for the
        source-framework EngineClient interface.
        """
        from audio_source.recorder import AudioRecorder
        from audio_source.transcriber import transcribe, is_hallucination

        keep_chunks = config.get("keep_chunks", False)
        chunk_duration = config.get("chunk_duration_seconds", 300)

        # pending_chunks: list of (path, timestamp, duration, source_label)
        pending_chunks: list[tuple[str, str, float, str]] = []
        lock = threading.Lock()

        def make_callback(source_label: str):
            def on_chunk_ready(chunk_path: str, start_timestamp: str, duration: float):
                logger.debug(
                    "chunk ready [%s]: %s (started=%s, duration=%.1fs)",
                    source_label, chunk_path, start_timestamp, duration,
                )
                with lock:
                    pending_chunks.append((chunk_path, start_timestamp, duration, source_label))
            return on_chunk_ready

        # Build recorders from config (default: single mic recorder)
        recorders = [AudioRecorder(chunk_seconds=chunk_duration)]
        for rec in recorders:
            t = threading.Thread(
                target=rec.record,
                args=(make_callback(rec.source),),
                daemon=True,
            )
            t.start()
            logger.info("recorder thread started: source=%s device=%s", rec.source, rec.device)

        # Main processing loop
        while True:
            try:
                if client.is_paused():
                    time.sleep(2)
                    continue

                with lock:
                    to_process = list(pending_chunks)
                    pending_chunks.clear()

                for chunk_path, start_timestamp, duration, source_label in to_process:
                    logger.info("processing chunk [%s]: %s", source_label, chunk_path)

                    try:
                        result = transcribe(chunk_path)
                    except Exception:
                        logger.exception("transcription failed for %s", chunk_path)
                        continue

                    text = result["text"]
                    language = result["language"]

                    if not text.strip():
                        logger.debug("empty transcription for %s, skipping", chunk_path)
                    elif is_hallucination(result):
                        logger.info("hallucination detected for %s, skipping", chunk_path)
                    else:
                        client.ingest({
                            "timestamp": start_timestamp,
                            "duration_seconds": duration,
                            "text": text,
                            "language": language,
                            "source": source_label,
                            "chunk_path": chunk_path if keep_chunks else "",
                        })

                    # Clean up chunk file
                    if not keep_chunks:
                        try:
                            os.remove(chunk_path)
                            logger.debug("deleted chunk: %s", chunk_path)
                        except OSError:
                            logger.warning("failed to delete chunk: %s", chunk_path)

            except Exception:
                logger.exception("error in audio source main loop")

            time.sleep(2)
