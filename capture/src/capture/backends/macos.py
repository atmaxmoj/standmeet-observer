"""macOS backend: Quartz (CoreGraphics) for capture, Vision for OCR, AppKit for window info."""

import hashlib
import io
import logging
import sys

import Quartz
import Vision
from AppKit import NSWorkspace
from PIL import Image

logger = logging.getLogger(__name__)


def check_screen_recording_permission() -> bool:
    """Check if the app has screen recording permission on macOS.

    Attempts a test screenshot of the main display. If CGDisplayCreateImage
    returns None, the permission has not been granted.
    """
    main_display = Quartz.CGMainDisplayID()
    test_image = Quartz.CGDisplayCreateImage(main_display)
    if test_image is None:
        logger.error(
            "Screen recording permission denied. "
            "Go to System Settings → Privacy & Security → Screen Recording "
            "and enable access for Terminal (or your terminal app)."
        )
        return False
    logger.info("Screen recording permission: OK")
    return True


# -- Display enumeration --


def get_all_displays() -> list[int]:
    """Enumerate all active displays. Returns list of display IDs."""
    max_displays = 16
    (err, display_ids, count) = Quartz.CGGetActiveDisplayList(max_displays, None, None)
    if err != 0:
        logger.error("CGGetActiveDisplayList failed with error %d", err)
        return [Quartz.CGMainDisplayID()]
    displays = list(display_ids[:count])
    logger.debug("found %d displays: %s", len(displays), displays)
    return displays


# -- Screen capture --


def capture_display(display_id: int) -> object | None:
    """Capture a screenshot of the given display. Returns CGImage or None."""
    image = Quartz.CGDisplayCreateImage(display_id)
    if image is None:
        logger.warning("CGDisplayCreateImage returned None for display %d", display_id)
        return None
    logger.debug(
        "captured display %d: %dx%d",
        display_id,
        Quartz.CGImageGetWidth(image),
        Quartz.CGImageGetHeight(image),
    )
    return image


# -- Image hashing --


def hash_image(image: object) -> str:
    """Compute SHA-256 hash of CGImage bitmap data for change detection."""
    data_provider = Quartz.CGImageGetDataProvider(image)
    if data_provider is None:
        return ""
    raw_data = Quartz.CGDataProviderCopyData(data_provider)
    if raw_data is None:
        return ""
    return hashlib.sha256(bytes(raw_data)).hexdigest()


# -- OCR --


def ocr_image(image: object) -> str:
    """Run OCR on a CGImage using Vision framework. Returns recognized text."""
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        image, None
    )

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    success = handler.performRequests_error_([request], None)
    if not success[0]:
        error = success[1]
        logger.warning("OCR failed: %s", error)
        return ""

    results = request.results()
    if not results:
        logger.debug("OCR returned no text")
        return ""

    lines = []
    for observation in results:
        candidate = observation.topCandidates_(1)
        if candidate:
            lines.append(candidate[0].string())

    text = "\n".join(lines)
    logger.debug("OCR recognized %d lines, %d chars", len(lines), len(text))
    return text


# -- Image compression --


def compress_image(image: object, max_width: int, quality: int) -> bytes:
    """Downscale CGImage and compress to WebP. Returns WebP bytes."""
    width = Quartz.CGImageGetWidth(image)
    height = Quartz.CGImageGetHeight(image)
    bpp = Quartz.CGImageGetBitsPerPixel(image)
    bpr = Quartz.CGImageGetBytesPerRow(image)

    # Get raw pixel data
    data_provider = Quartz.CGImageGetDataProvider(image)
    raw_data = Quartz.CGDataProviderCopyData(data_provider)

    # CGImage is typically BGRA
    pil_image = Image.frombytes("RGBA", (width, height), bytes(raw_data), "raw", "BGRA", bpr)

    # Downscale
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        pil_image = pil_image.resize((max_width, new_height), Image.LANCZOS)

    # Convert RGBA → RGB (WebP lossy doesn't need alpha for screenshots)
    pil_image = pil_image.convert("RGB")

    buf = io.BytesIO()
    pil_image.save(buf, format="webp", quality=quality)
    webp_bytes = buf.getvalue()
    logger.debug(
        "compressed %dx%d → %dx%d, %d bytes WebP (q=%d)",
        width, height, pil_image.width, pil_image.height, len(webp_bytes), quality,
    )
    return webp_bytes


# -- Frontmost app --


def get_frontmost_app() -> tuple[str, str]:
    """Return (app_name, window_title) of the frontmost application."""
    app_name = ""
    window_title = ""

    try:
        workspace = NSWorkspace.sharedWorkspace()
        front_app = workspace.frontmostApplication()
        if front_app:
            app_name = front_app.localizedName() or ""
            pid = front_app.processIdentifier()

            window_list = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
            )
            if window_list:
                for window in window_list:
                    if window.get("kCGWindowOwnerPID") == pid:
                        title = window.get("kCGWindowName", "")
                        if title:
                            window_title = title
                            break

    except Exception:
        logger.exception("failed to get frontmost app info")

    logger.debug("frontmost app: %s / %s", app_name, window_title)
    return app_name, window_title
