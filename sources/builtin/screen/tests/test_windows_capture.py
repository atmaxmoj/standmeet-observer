"""Integration tests for Windows screen capture backend.

Runs on Windows only (GitHub Actions windows-latest runner).
Tests the full capture pipeline: screenshot, hash, OCR, compress.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture(scope="module")
def backends():
    """Import the Windows backend functions."""
    from screen_source.backends import (
        autorelease_pool,
        capture_display,
        compress_image,
        get_all_displays,
        get_frontmost_app,
        hash_image,
        ocr_image,
    )
    return {
        "autorelease_pool": autorelease_pool,
        "capture_display": capture_display,
        "compress_image": compress_image,
        "get_all_displays": get_all_displays,
        "get_frontmost_app": get_frontmost_app,
        "hash_image": hash_image,
        "ocr_image": ocr_image,
    }


class TestWindowsImports:
    """Verify all Windows dependencies can be imported."""

    def test_import_mss(self):
        import mss
        import mss.tools
        assert mss is not None

    def test_import_pillow(self):
        from PIL import Image
        assert Image is not None

    def test_import_rapidocr(self):
        from rapidocr_onnxruntime import RapidOCR
        assert RapidOCR is not None

    def test_import_backends(self):
        from screen_source.backends import (
            capture_display,
            compress_image,
            get_all_displays,
            get_frontmost_app,
            hash_image,
            ocr_image,
        )
        assert all([
            capture_display, compress_image, get_all_displays,
            get_frontmost_app, hash_image, ocr_image,
        ])


class TestWindowsCapture:
    """Test the capture pipeline on a real Windows desktop."""

    def test_get_all_displays(self, backends):
        displays = backends["get_all_displays"]()
        assert isinstance(displays, list)
        assert len(displays) >= 1, "Should detect at least 1 display"
        assert all(isinstance(d, int) for d in displays)

    def test_capture_display_returns_bytes(self, backends):
        displays = backends["get_all_displays"]()
        image = backends["capture_display"](displays[0])
        # On headless CI, capture may return None or a valid screenshot
        if image is not None:
            assert isinstance(image, bytes)
            assert len(image) > 0

    def test_hash_image(self, backends):
        displays = backends["get_all_displays"]()
        image = backends["capture_display"](displays[0])
        if image is None:
            pytest.skip("capture returned None (headless?)")
        h = backends["hash_image"](image)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_hash_same_image_is_stable(self, backends):
        displays = backends["get_all_displays"]()
        image = backends["capture_display"](displays[0])
        if image is None:
            pytest.skip("capture returned None (headless?)")
        h1 = backends["hash_image"](image)
        h2 = backends["hash_image"](image)
        assert h1 == h2

    def test_ocr_image(self, backends):
        displays = backends["get_all_displays"]()
        image = backends["capture_display"](displays[0])
        if image is None:
            pytest.skip("capture returned None (headless?)")
        text = backends["ocr_image"](image)
        assert isinstance(text, str)
        # Don't assert text is non-empty — headless desktop may be blank

    def test_compress_image(self, backends):
        displays = backends["get_all_displays"]()
        image = backends["capture_display"](displays[0])
        if image is None:
            pytest.skip("capture returned None (headless?)")
        webp = backends["compress_image"](image, max_width=512, quality=50)
        assert isinstance(webp, bytes)
        assert len(webp) > 0
        assert len(webp) < len(image), "WebP should be smaller than PNG"

    def test_get_frontmost_app(self, backends):
        app_name, window_title = backends["get_frontmost_app"]()
        assert isinstance(app_name, str)
        assert isinstance(window_title, str)
        # Values may be empty on headless, just verify no crash

    def test_autorelease_pool_is_noop(self, backends):
        """On Windows, autorelease_pool should be a no-op context manager."""
        with backends["autorelease_pool"]():
            pass  # Should not raise


class TestWindowsMemory:
    """Verify no memory leak over repeated captures."""

    def test_no_memory_leak_over_100_captures(self, backends):
        """Capture 100 times and verify RSS doesn't grow unboundedly."""
        displays = backends["get_all_displays"]()
        image = backends["capture_display"](displays[0])
        if image is None:
            pytest.skip("capture returned None (headless?)")

        def get_rss_mb() -> float:
            """Get current process RSS in MB via Win32 API."""
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(pmc), pmc.cb,
            )
            return pmc.WorkingSetSize / 1024 / 1024

        # Warm up
        for _ in range(5):
            img = backends["capture_display"](displays[0])
            if img:
                backends["hash_image"](img)
                backends["compress_image"](img, 512, 50)
            del img

        baseline_mb = get_rss_mb()

        # Run 100 capture cycles
        for i in range(100):
            with backends["autorelease_pool"]():
                img = backends["capture_display"](displays[0])
                if img:
                    backends["hash_image"](img)
                    if i % 10 == 0:
                        backends["ocr_image"](img)
                    backends["compress_image"](img, 1024, 80)
                del img

        final_mb = get_rss_mb()
        growth = final_mb - baseline_mb
        print(f"Memory: baseline={baseline_mb:.0f}MB final={final_mb:.0f}MB growth={growth:.0f}MB")

        # Allow some growth but not unbounded (< 200MB for 100 captures)
        assert growth < 200, f"Memory grew {growth:.0f}MB over 100 captures — possible leak"
