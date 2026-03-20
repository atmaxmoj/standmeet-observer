"""Tests for Frame dataclass."""

from engine.etl.entities import Frame


class TestFrame:
    def test_create_capture_frame(self):
        f = Frame(
            id=1, source="capture", text="hello world",
            app_name="VSCode", window_name="editor",
            timestamp="2026-03-14T10:00:00+00:00",
            image_path="frames/2026-03-14/100000_d1.webp",
        )
        assert f.source == "capture"
        assert f.image_path == "frames/2026-03-14/100000_d1.webp"

    def test_create_audio_frame(self):
        f = Frame(
            id=1, source="audio", text="hello",
            app_name="microphone", window_name="audio/en",
            timestamp="2026-03-14T10:00:00+00:00",
        )
        assert f.source == "audio"
        assert f.image_path == ""

    def test_default_image_path(self):
        f = Frame(
            id=1, source="capture", text="t",
            app_name="a", window_name="w",
            timestamp="t",
        )
        assert f.image_path == ""
