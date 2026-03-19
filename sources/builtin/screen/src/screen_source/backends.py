"""Platform dispatch: exports unified capture interface regardless of OS."""

import sys

if sys.platform == "darwin":
    from screen_source.macos import (
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
else:
    raise RuntimeError(
        f"Unsupported platform: {sys.platform}. "
        "Capture daemon supports macOS and Windows only."
    )

__all__ = [
    "get_all_displays",
    "capture_display",
    "compress_image",
    "hash_image",
    "ocr_image",
    "get_frontmost_app",
]
