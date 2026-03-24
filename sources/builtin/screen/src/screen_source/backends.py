"""Platform dispatch: exports unified capture interface regardless of OS."""

import contextlib
import sys

if sys.platform == "darwin":
    from screen_source.macos import (
        autorelease_pool,
        capture_display,
        compress_image,
        get_all_displays,
        get_frontmost_app,
        hash_image,
        ocr_image,
    )
elif sys.platform == "win32":
    from screen_source.windows import (
        capture_display,
        compress_image,
        get_all_displays,
        get_frontmost_app,
        hash_image,
        ocr_image,
    )

    @contextlib.contextmanager
    def autorelease_pool():
        yield
else:
    raise RuntimeError(
        f"Unsupported platform: {sys.platform}. "
        "Capture daemon supports macOS and Windows only."
    )

__all__ = [
    "autorelease_pool",
    "get_all_displays",
    "capture_display",
    "compress_image",
    "hash_image",
    "ocr_image",
    "get_frontmost_app",
]
