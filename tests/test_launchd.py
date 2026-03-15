"""Tests for launchd plist generation."""

import sys
from pathlib import Path

# Add cli.py's directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli import _launchd_plist, _plist_path


class TestLaunchdPlist:
    def test_plist_contains_label(self):
        plist = _launchd_plist("capture", Path("/tmp/capture"))
        assert "com.observer.capture" in plist

    def test_plist_contains_keep_alive(self):
        plist = _launchd_plist("capture", Path("/tmp/capture"))
        assert "<key>KeepAlive</key>" in plist
        assert "<true/>" in plist

    def test_plist_contains_working_directory(self):
        plist = _launchd_plist("audio", Path("/foo/bar/audio"))
        assert "/foo/bar/audio" in plist

    def test_plist_contains_throttle_interval(self):
        plist = _launchd_plist("capture", Path("/tmp"))
        assert "<key>ThrottleInterval</key>" in plist
        assert "<integer>10</integer>" in plist

    def test_plist_contains_uv_command(self):
        plist = _launchd_plist("capture", Path("/tmp"))
        assert "<string>uv</string>" in plist or "uv" in plist
        assert "<string>-m</string>" in plist
        assert "<string>capture</string>" in plist

    def test_plist_path(self):
        p = _plist_path("capture")
        assert p.name == "com.observer.capture.plist"
        assert "LaunchAgents" in str(p)
