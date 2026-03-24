"""Screen capture source plugin — screenshot + OCR of all displays.

Custom start() loop because the capture cycle is:
  screenshot → hash (skip if unchanged) → OCR → compress → save → ingest

This differs from the default poll loop which just calls collect() repeatedly.
Backend code currently lives in capture/src/capture/backends/ and will be
migrated into this plugin in Phase 2.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from source_framework.plugin import SourcePlugin, ProbeResult

logger = logging.getLogger(__name__)


def _check_screen_recording_permission() -> tuple[bool, str]:
    """Check if screen recording permission is granted on macOS.

    Returns (available, message).
    """
    try:
        from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
        # If we can read window names, permission is granted
        has_names = any(
            w.get("kCGWindowName") is not None
            for w in (windows or [])
        )
        if has_names:
            return True, "screen recording permission granted"
        else:
            return False, (
                "screen recording permission may not be granted — "
                "no window names accessible. Grant permission in "
                "System Settings → Privacy & Security → Screen Recording"
            )
    except ImportError:
        return False, "pyobjc-framework-Quartz not installed"
    except Exception as e:
        return False, f"permission check failed: {e}"


def _save_frame(frames_dir: str, webp_bytes: bytes, timestamp: str, display_id: int) -> str:
    """Save compressed WebP frame to disk. Returns relative path."""
    dt = datetime.fromisoformat(timestamp)
    date_dir = Path(frames_dir) / dt.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dt.strftime('%H%M%S')}_{dt.microsecond // 1000:03d}_d{display_id}.webp"
    path = date_dir / filename
    path.write_bytes(webp_bytes)
    return str(path.relative_to(Path(frames_dir).parent))


class ScreenSource(SourcePlugin):
    """Captures screenshots of all displays, runs OCR, and ingests frames.

    Overrides start() because the capture cycle (screenshot → hash → OCR →
    compress → save → ingest) is more complex than a simple collect() call.
    """

    def probe(self) -> ProbeResult:
        """Check platform support and screen recording permission."""
        if sys.platform == "darwin":
            ok, msg = _check_screen_recording_permission()
            return ProbeResult(
                available=ok,
                source="screen",
                description=msg,
                warnings=[] if ok else [msg],
            )
        elif sys.platform == "win32":
            # Windows doesn't require special permission for screenshots
            return ProbeResult(
                available=True,
                source="screen",
                description="Windows screen capture available",
            )
        else:
            return ProbeResult(
                available=False,
                source="screen",
                description=f"unsupported platform: {sys.platform}",
                warnings=[f"screen capture requires macOS or Windows, got {sys.platform}"],
            )

    def collect(self) -> list[dict]:
        """Stub — the custom start() handles the full capture cycle.

        This exists only to satisfy the SourcePlugin ABC. The actual capture
        logic lives in start() because it needs hash-based dedup, OCR, image
        compression, and file saving — none of which fit the simple
        collect-then-ingest pattern.
        """
        return []

    def start(self, client: "EngineClient", config: dict):
        """Main capture loop: screenshot → hash → OCR → compress → save → ingest.

        Mirrors the logic from capture/src/capture/daemon.py but runs within
        the source plugin framework.
        """
        from screen_source.backends import (
            autorelease_pool,
            capture_display,
            compress_image,
            get_all_displays,
            get_frontmost_app,
            hash_image,
            ocr_image,
        )

        interval = config.get("interval_seconds", 3)
        max_width = config.get("max_width", 1024)
        webp_quality = config.get("webp_quality", 80)

        # Resolve frames directory
        data_dir = Path(os.environ.get(
            "OBSERVER_DATA_DIR", str(Path.home() / ".observer"),
        ))
        frames_dir = str(data_dir / "frames")
        Path(frames_dir).mkdir(parents=True, exist_ok=True)

        last_hashes: dict[int, str] = {}

        logger.info(
            "screen source started: interval=%ds, max_width=%d, quality=%d",
            interval, max_width, webp_quality,
        )

        while True:
            if client.is_paused():
                time.sleep(interval)
                continue

            try:
                cycle_start = time.monotonic()

                # Wrap entire cycle in NSAutoreleasePool so CoreGraphics/Vision
                # ObjC objects are released at end of each cycle, not leaked.
                with autorelease_pool():
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
                            del image
                            continue

                        text = ocr_image(image)

                        # Compress and save frame
                        image_path = ""
                        try:
                            webp_bytes = compress_image(image, max_width, webp_quality)
                            image_path = _save_frame(frames_dir, webp_bytes, timestamp, display_id)
                        except Exception:
                            logger.exception("failed to compress/save frame for display %d", display_id)

                        client.ingest({
                            "timestamp": timestamp,
                            "app_name": app_name,
                            "window_name": window_name,
                            "text": text,
                            "display_id": display_id,
                            "image_hash": current_hash,
                            "image_path": image_path,
                        })

                        last_hashes[display_id] = current_hash
                        captured += 1
                        del image

                elapsed = time.monotonic() - cycle_start
                logger.debug(
                    "cycle: captured=%d skipped=%d elapsed=%.1fms",
                    captured, skipped, elapsed * 1000,
                )

            except Exception:
                logger.exception("error in screen capture cycle")

            time.sleep(interval)
