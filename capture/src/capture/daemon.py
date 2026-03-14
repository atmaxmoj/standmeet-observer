"""Main capture loop: screenshot → hash → OCR if changed → compress → push to engine.
Also collects OS events (shell commands, browser URLs)."""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from capture.backends import (
    capture_display,
    compress_image,
    get_all_displays,
    get_frontmost_app,
    hash_image,
    ocr_image,
)
from capture.collectors import get_all_collectors
from capture.config import CAPTURE_INTERVAL, FRAME_MAX_WIDTH, FRAMES_DIR, WEBP_QUALITY
from capture.engine_client import EngineClient

logger = logging.getLogger(__name__)


def _save_frame(webp_bytes: bytes, timestamp: str, display_id: int) -> str:
    """Save compressed WebP frame to disk. Returns relative path."""
    dt = datetime.fromisoformat(timestamp)
    date_dir = Path(FRAMES_DIR) / dt.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dt.strftime('%H%M%S')}_{dt.microsecond // 1000:03d}_d{display_id}.webp"
    path = date_dir / filename
    path.write_bytes(webp_bytes)
    return str(path.relative_to(Path(FRAMES_DIR).parent))


def run(client: EngineClient):
    """Main capture loop. Runs forever until interrupted."""
    last_hashes: dict[int, str] = {}
    Path(FRAMES_DIR).mkdir(parents=True, exist_ok=True)

    # Initialize OS event collectors
    collectors = []
    for c in get_all_collectors():
        if c.available():
            collectors.append(c)
            logger.info("collector enabled: %s/%s", c.event_type, c.source)
        else:
            logger.debug("collector skipped (not available): %s/%s", c.event_type, c.source)

    logger.info(
        "capture daemon started: interval=%ds, displays=%d, collectors=%d",
        CAPTURE_INTERVAL,
        len(get_all_displays()),
        len(collectors),
    )

    while True:
        try:
            cycle_start = time.monotonic()
            displays = get_all_displays()
            app_name, window_name = get_frontmost_app()
            timestamp = datetime.now(timezone.utc).isoformat()

            captured = 0
            skipped = 0

            for display_id in displays:
                image = capture_display(display_id)
                if image is None:
                    continue

                current_hash = hash_image(image)
                if current_hash == last_hashes.get(display_id):
                    skipped += 1
                    logger.debug("display %d unchanged, skipping OCR", display_id)
                    continue

                text = ocr_image(image)

                # Compress and save frame
                image_path = ""
                try:
                    webp_bytes = compress_image(image, FRAME_MAX_WIDTH, WEBP_QUALITY)
                    image_path = _save_frame(webp_bytes, timestamp, display_id)
                except Exception:
                    logger.exception("failed to compress/save frame for display %d", display_id)

                client.insert_frame(
                    timestamp=timestamp,
                    app_name=app_name,
                    window_name=window_name,
                    text=text,
                    display_id=display_id,
                    image_hash=current_hash,
                    image_path=image_path,
                )
                last_hashes[display_id] = current_hash
                captured += 1

            # Collect OS events
            os_events = 0
            for collector in collectors:
                try:
                    entries = collector.collect()
                    for data in entries:
                        client.insert_os_event(
                            timestamp=timestamp,
                            event_type=collector.event_type,
                            source=collector.source,
                            data=data,
                        )
                        os_events += 1
                except Exception:
                    logger.exception("collector %s/%s failed", collector.event_type, collector.source)

            elapsed = time.monotonic() - cycle_start
            logger.debug(
                "cycle: captured=%d skipped=%d os_events=%d elapsed=%.1fms",
                captured, skipped, os_events, elapsed * 1000,
            )

        except Exception:
            logger.exception("error in capture cycle")

        time.sleep(CAPTURE_INTERVAL)
