"""Observation entities — raw data from source plugins."""

from dataclasses import dataclass


@dataclass
class Frame:
    """A single observation from any source.

    source: where this came from ("capture", "audio", "os_event", or manifest source name)
    app_name: the application context (for capture: the focused app)
    text: the signal content (OCR text, transcription, event data)
    image_path: relative path to compressed screenshot (empty if no image)
    """
    id: int
    source: str
    text: str
    app_name: str
    window_name: str
    timestamp: str
    image_path: str = ""
