"""HTTP client for pushing data to the engine API."""

import logging
import urllib.error
import urllib.request
import json

logger = logging.getLogger(__name__)


class EngineClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, data: dict) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            logger.warning("engine API unreachable (%s): %s", url, e)
            return {}
        except Exception:
            logger.exception("engine API error (%s)", url)
            return {}

    def insert_audio_frame(
        self,
        timestamp: str,
        duration_seconds: float,
        text: str,
        language: str,
        source: str = "mic",
        chunk_path: str = "",
    ) -> int:
        result = self._post("/ingest/audio", {
            "timestamp": timestamp,
            "duration_seconds": duration_seconds,
            "text": text,
            "language": language,
            "source": source,
            "chunk_path": chunk_path,
        })
        return result.get("id", 0)
