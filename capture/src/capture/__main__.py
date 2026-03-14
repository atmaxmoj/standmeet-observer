"""Entry point: python -m capture"""

import logging
import signal
import sys

from capture.config import DB_PATH, LOG_LEVEL
from capture.daemon import run
from capture.db import CaptureDB

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("capture")


def main():
    # Check screen recording permission before starting
    if sys.platform == "darwin":
        from capture.backends.macos import check_screen_recording_permission
        if not check_screen_recording_permission():
            sys.exit(1)

    db = CaptureDB(DB_PATH)
    db.connect()

    def shutdown(sig, frame):
        logger.info("shutting down (signal %d)", sig)
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        run(db)
    except KeyboardInterrupt:
        logger.info("interrupted")
    finally:
        db.close()


if __name__ == "__main__":
    main()
