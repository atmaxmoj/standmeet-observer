"""Entry point: python -m capture"""

import logging
import signal
import sys

from capture.config import ENGINE_URL, LOG_LEVEL
from capture.daemon import run
from capture.engine_client import EngineClient

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

    client = EngineClient(ENGINE_URL)
    logger.info("engine API: %s", ENGINE_URL)

    def shutdown(sig, frame):
        logger.info("shutting down (signal %d)", sig)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        run(client)
    except KeyboardInterrupt:
        logger.info("interrupted")


if __name__ == "__main__":
    main()
