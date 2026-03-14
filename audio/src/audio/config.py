import os
from pathlib import Path

# Shared DB with capture daemon
DB_PATH = os.environ.get(
    "CAPTURE_DB_PATH",
    str(Path.home() / ".bisimulator" / "capture.db"),
)

# Recording settings
SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", "16000"))
CHANNELS = int(os.environ.get("AUDIO_CHANNELS", "1"))
CHUNK_DURATION_SECONDS = int(os.environ.get("AUDIO_CHUNK_SECONDS", "300"))  # 5 min

# Whisper settings
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", None)  # None = auto-detect

# Paths
CHUNKS_DIR = os.environ.get(
    "AUDIO_CHUNKS_DIR",
    str(Path.home() / ".bisimulator" / "audio_chunks"),
)

# Output device for system audio capture (e.g. "BlackHole 2ch" on macOS)
# Leave empty to only record microphone input
AUDIO_OUTPUT_DEVICE = os.environ.get("AUDIO_OUTPUT_DEVICE", "")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
