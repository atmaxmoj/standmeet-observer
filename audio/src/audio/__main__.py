"""Entry point: python -m audio"""

import logging
import signal
import sys

from audio.config import AUDIO_OUTPUT_DEVICE, DB_PATH, LOG_LEVEL
from audio.daemon import run
from audio.db import AudioDB
from audio.recorder import AudioRecorder

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("audio")


def main():
    db = AudioDB(DB_PATH)
    db.connect()

    recorders = []

    # Microphone input (always enabled)
    mic_recorder = AudioRecorder(source="mic")
    recorders.append(mic_recorder)

    # System audio output (if configured)
    if AUDIO_OUTPUT_DEVICE:
        logger.info("output device configured: %s", AUDIO_OUTPUT_DEVICE)
        speaker_recorder = AudioRecorder(
            device=AUDIO_OUTPUT_DEVICE,
            source="speaker",
        )
        recorders.append(speaker_recorder)
    else:
        logger.info("no output device configured, recording mic only")

    def shutdown(sig, frame):
        logger.info("shutting down (signal %d)", sig)
        for rec in recorders:
            rec.stop()
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        run(db, recorders)
    except KeyboardInterrupt:
        logger.info("interrupted")
    finally:
        for rec in recorders:
            rec.stop()
        db.close()


if __name__ == "__main__":
    main()
