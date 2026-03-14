import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("BISIMULATOR_DATA_DIR", str(Path.home() / ".bisimulator")))

ENGINE_URL = os.environ.get("ENGINE_URL", "http://localhost:5001")

FRAMES_DIR = str(DATA_DIR / "frames")

CAPTURE_INTERVAL = int(os.environ.get("CAPTURE_INTERVAL", "3"))

# WebP compression quality (0-100). 80 is a good balance for screenshots with text.
WEBP_QUALITY = int(os.environ.get("WEBP_QUALITY", "80"))

# Max width for downscaled frames. Height scales proportionally.
FRAME_MAX_WIDTH = int(os.environ.get("FRAME_MAX_WIDTH", "1024"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
