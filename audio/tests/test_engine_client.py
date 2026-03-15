"""Tests for EngineClient pause detection."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from audio.engine_client import EngineClient


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
        pass


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
