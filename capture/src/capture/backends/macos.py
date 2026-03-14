"""macOS backend: Quartz (CoreGraphics) for capture, Vision for OCR, AppKit for window info."""

import hashlib
import logging

import Quartz
import Vision
from AppKit import NSWorkspace

logger = logging.getLogger(__name__)


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
