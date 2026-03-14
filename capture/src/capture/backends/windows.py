"""Windows backend: mss for capture, RapidOCR for OCR, win32gui for window info."""

import hashlib
import io
import logging

import mss
import mss.tools
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger(__name__)

_ocr_engine: RapidOCR | None = None
_sct: mss.mss | None = None


def _get_sct() -> mss.mss:
    """Lazy-init mss screenshot instance."""
    global _sct
    if _sct is None:
        _sct = mss.mss()
        logger.debug("mss initialized, monitors: %d", len(_sct.monitors) - 1)
    return _sct


def _get_ocr() -> RapidOCR:
    """Lazy-init RapidOCR engine."""
    global _ocr_engine
    if _ocr_engine is None:
        logger.info("initializing RapidOCR engine (first call may be slow)")
        _ocr_engine = RapidOCR()
        logger.info("RapidOCR engine ready")
    return _ocr_engine


# -- Display enumeration --


def get_all_displays() -> list[int]:
    """Enumerate all active monitors. Returns list of 1-based monitor indices."""
    sct = _get_sct()
    # monitors[0] is the virtual combined screen, [1:] are individual monitors
    count = len(sct.monitors) - 1
    displays = list(range(1, count + 1))
    logger.debug("found %d displays: %s", len(displays), displays)
    return displays


# -- Screen capture --


def capture_display(display_id: int) -> bytes | None:
    """Capture a screenshot of the given monitor. Returns PNG bytes or None."""
    sct = _get_sct()
    try:
        monitor = sct.monitors[display_id]
        screenshot = sct.grab(monitor)
        # Convert to PNG bytes
        png_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)
        logger.debug(
            "captured display %d: %dx%d (%d bytes)",
            display_id, screenshot.width, screenshot.height, len(png_bytes),
        )
        return png_bytes
    except Exception:
        logger.exception("failed to capture display %d", display_id)
        return None


# -- Image hashing --


def hash_image(image: bytes) -> str:
    """Compute SHA-256 hash of image bytes for change detection."""
    return hashlib.sha256(image).hexdigest()


# -- OCR --


def ocr_image(image: bytes) -> str:
    """Run OCR on PNG image bytes using RapidOCR. Returns recognized text."""
    ocr = _get_ocr()

    try:
        # RapidOCR accepts numpy array, PIL Image, or file path
        pil_image = Image.open(io.BytesIO(image))
        result, _ = ocr(pil_image)

        if not result:
            logger.debug("OCR returned no text")
            return ""

        # result is list of [bbox, text, confidence]
        lines = [item[1] for item in result if item[1]]
        text = "\n".join(lines)
        logger.debug("OCR recognized %d lines, %d chars", len(lines), len(text))
        return text

    except Exception:
        logger.exception("OCR failed")
        return ""


# -- Image compression --


def compress_image(image: bytes, max_width: int, quality: int) -> bytes:
    """Downscale PNG bytes and compress to WebP. Returns WebP bytes."""
    pil_image = Image.open(io.BytesIO(image))
    width, height = pil_image.size

    # Downscale
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        pil_image = pil_image.resize((max_width, new_height), Image.LANCZOS)

    # Ensure RGB
    if pil_image.mode != "RGB":
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
    """Return (app_name, window_title) of the foreground window."""
    app_name = ""
    window_title = ""

    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Get foreground window
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return app_name, window_title

        # Get window title
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            window_title = buf.value

        # Get process name
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
        )
        if handle:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.wintypes.DWORD(260)
            kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            kernel32.CloseHandle(handle)
            # Extract just the exe name without path
            full_path = buf.value
            if full_path:
                app_name = full_path.rsplit("\\", 1)[-1].replace(".exe", "")

    except Exception:
        logger.exception("failed to get frontmost app info")

    logger.debug("frontmost app: %s / %s", app_name, window_title)
    return app_name, window_title
