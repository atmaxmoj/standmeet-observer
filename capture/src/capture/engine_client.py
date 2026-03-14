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

    def insert_frame(
        self,
        timestamp: str,
        app_name: str,
        window_name: str,
        text: str,
        display_id: int,
        image_hash: str,
        image_path: str = "",
    ) -> int:
        result = self._post("/ingest/frame", {
            "timestamp": timestamp,
            "app_name": app_name,
            "window_name": window_name,
            "text": text,
            "display_id": display_id,
            "image_hash": image_hash,
            "image_path": image_path,
        })
        return result.get("id", 0)

    def insert_os_event(
        self,
        timestamp: str,
        event_type: str,
        source: str,
        data: str,
    ) -> int:
        result = self._post("/ingest/os-event", {
            "timestamp": timestamp,
            "event_type": event_type,
            "source": source,
            "data": data,
        })
        return result.get("id", 0)
