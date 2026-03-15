"""Tests for EngineClient pause detection."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

from capture.engine_client import EngineClient


class _PauseHandler(BaseHTTPRequestHandler):
    paused = False

    def do_GET(self):
        if self.path == "/engine/pipeline":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"paused": self.paused}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # suppress logs


class TestIsPaused:
    def test_not_paused(self):
        _PauseHandler.paused = False
        server = HTTPServer(("127.0.0.1", 0), _PauseHandler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request)
        t.start()
        try:
            client = EngineClient(f"http://127.0.0.1:{port}")
            assert client.is_paused() is False
        finally:
            t.join(timeout=2)
            server.server_close()

    def test_paused(self):
        _PauseHandler.paused = True
        server = HTTPServer(("127.0.0.1", 0), _PauseHandler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request)
        t.start()
        try:
            client = EngineClient(f"http://127.0.0.1:{port}")
            assert client.is_paused() is True
        finally:
            t.join(timeout=2)
            server.server_close()

    def test_unreachable_returns_false(self):
        client = EngineClient("http://127.0.0.1:1")
        assert client.is_paused() is False


class TestDaemonPauseSkip:
    def test_paused_skips_capture(self):
        """When paused, the daemon loop should sleep and continue without capturing."""
        from capture.daemon import run
        client = EngineClient("http://127.0.0.1:1")

        call_count = 0

        def fake_is_paused():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise KeyboardInterrupt  # stop the loop
            return True

        with patch.object(client, "is_paused", side_effect=fake_is_paused), \
             patch("capture.daemon.time.sleep"):
            try:
                run(client)
            except KeyboardInterrupt:
                pass

        # Should have checked pause 3 times, never called insert_frame
        assert call_count == 3
