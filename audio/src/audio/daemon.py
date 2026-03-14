"""Audio capture daemon: record → chunk → transcribe → write to DB."""

import logging
import os
import threading
import time

from audio.db import AudioDB
from audio.recorder import AudioRecorder
from audio.transcriber import transcribe, is_hallucination

logger = logging.getLogger(__name__)


def run(db: AudioDB, recorders: list[AudioRecorder], keep_chunks: bool = False):
    """
    Main daemon loop:
    1. Recorders run in background, producing WAV chunks every N minutes
    2. When a chunk is ready, transcribe it with whisper
    3. Write transcription segments to DB as audio_frames
    4. Optionally delete the WAV chunk to save disk space
    """
    # (path, timestamp, duration, source)
    pending_chunks: list[tuple[str, str, float, str]] = []
    lock = threading.Lock()

    def make_callback(source: str):
        def on_chunk_ready(chunk_path: str, start_timestamp: str, duration: float):
            logger.debug(
                "chunk ready [%s]: %s (started=%s, duration=%.1fs)",
                source, chunk_path, start_timestamp, duration,
            )
            with lock:
                pending_chunks.append((chunk_path, start_timestamp, duration, source))
        return on_chunk_ready

    # Start all recorders in background threads
    for rec in recorders:
        t = threading.Thread(
            target=rec.record,
            args=(make_callback(rec.source),),
            daemon=True,
        )
        t.start()
        logger.info("recorder thread started: source=%s device=%s", rec.source, rec.device)

    # Main loop: process pending chunks
    while True:
        try:
            with lock:
                to_process = list(pending_chunks)
                pending_chunks.clear()

            for chunk_path, start_timestamp, duration, source in to_process:
                logger.info("processing chunk [%s]: %s", source, chunk_path)

                try:
                    result = transcribe(chunk_path)
                except Exception:
                    logger.exception("transcription failed for %s", chunk_path)
                    continue

                text = result["text"]
                language = result["language"]

                if not text.strip():
                    logger.debug("empty transcription for %s, skipping DB write", chunk_path)
                elif is_hallucination(result):
                    logger.info("hallucination detected for %s, skipping DB write", chunk_path)
                else:
                    db.insert_audio_frame(
                        timestamp=start_timestamp,
                        duration_seconds=duration,
                        text=text,
                        language=language,
                        source=source,
                        chunk_path=chunk_path if keep_chunks else "",
                    )

                # Clean up chunk file
                if not keep_chunks:
                    try:
                        os.remove(chunk_path)
                        logger.debug("deleted chunk: %s", chunk_path)
                    except OSError:
                        logger.warning("failed to delete chunk: %s", chunk_path)

        except Exception:
            logger.exception("error in audio daemon main loop")

        time.sleep(2)
