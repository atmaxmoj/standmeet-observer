"""Tests for SourcePlugin ABC and ProbeResult."""

import pytest

from source_framework.plugin import SourcePlugin, ProbeResult


class TestProbeResult:
    def test_summary_ok(self):
        r = ProbeResult(
            available=True,
            source="zsh",
            description="found history",
            paths=["/home/user/.zsh_history"],
        )
        s = r.summary()
        assert "[OK]" in s
        assert "zsh" in s
        assert "found history" in s
        assert "/home/user/.zsh_history" in s

    def test_summary_skip(self):
        r = ProbeResult(
            available=False,
            source="chrome",
            description="not running",
            warnings=["Chrome not found"],
        )
        s = r.summary()
        assert "[SKIP]" in s
        assert "chrome" in s
        assert "warn: Chrome not found" in s

    def test_summary_no_extras(self):
        r = ProbeResult(available=True, source="test", description="ok")
        s = r.summary()
        assert s == "[OK] test: ok"


class TestSourcePlugin:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            SourcePlugin()

    def test_concrete_plugin(self):
        class DummySource(SourcePlugin):
            def probe(self) -> ProbeResult:
                return ProbeResult(available=True, source="dummy", description="ok")

            def collect(self) -> list[dict]:
                return [{"timestamp": "2026-01-01T00:00:00Z", "data": "test"}]

        plugin = DummySource()
        result = plugin.probe()
        assert result.available
        assert result.source == "dummy"

        records = plugin.collect()
        assert len(records) == 1
        assert records[0]["data"] == "test"

    def test_missing_probe_raises(self):
        with pytest.raises(TypeError):
            class BadSource(SourcePlugin):
                def collect(self) -> list[dict]:
                    return []
            BadSource()

    def test_missing_collect_raises(self):
        with pytest.raises(TypeError):
            class BadSource(SourcePlugin):
                def probe(self) -> ProbeResult:
                    return ProbeResult(available=True, source="x", description="x")
            BadSource()


class TestPauseControl:
    """Pipeline pause button should stop source collection."""

    def test_skips_collect_when_paused(self):
        """When pipeline is paused, start() should not call collect()."""

        class CountingSource(SourcePlugin):
            collect_count = 0

            def probe(self):
                return ProbeResult(available=True, source="test", description="ok")

            def collect(self):
                self.collect_count += 1
                return [{"timestamp": "2026-01-01T00:00:00Z"}]

        class MockClient:
            def __init__(self):
                self.paused = True
                self.ingested = []
                self._tick = 0

            def is_paused(self):
                self._tick += 1
                if self._tick >= 3:
                    raise SystemExit(0)  # stop after 3 checks
                return self.paused

            def ingest(self, record):
                self.ingested.append(record)

        plugin = CountingSource()
        client = MockClient()

        import source_framework.plugin as plugin_mod
        import time as _time
        original_sleep = _time.sleep
        _time.sleep = lambda _: None  # skip waits
        try:
            try:
                plugin.start(client, {"interval_seconds": 1})
            except SystemExit:
                pass
        finally:
            _time.sleep = original_sleep

        assert plugin.collect_count == 0, "collect() should not be called when paused"
        assert len(client.ingested) == 0

    def test_collects_when_not_paused(self):
        """When pipeline is not paused, start() should call collect() and ingest."""

        class CountingSource(SourcePlugin):
            collect_count = 0

            def probe(self):
                return ProbeResult(available=True, source="test", description="ok")

            def collect(self):
                self.collect_count += 1
                return [{"timestamp": "2026-01-01T00:00:00Z"}]

        class MockClient:
            def __init__(self):
                self.paused = False
                self.ingested = []
                self._tick = 0

            def is_paused(self):
                self._tick += 1
                if self._tick >= 3:
                    raise SystemExit(0)
                return self.paused

            def ingest(self, record):
                self.ingested.append(record)

        plugin = CountingSource()
        client = MockClient()

        import time as _time
        original_sleep = _time.sleep
        _time.sleep = lambda _: None
        try:
            try:
                plugin.start(client, {"interval_seconds": 1})
            except SystemExit:
                pass
        finally:
            _time.sleep = original_sleep

        assert plugin.collect_count == 2, f"Expected 2 collects, got {plugin.collect_count}"
        assert len(client.ingested) == 2

    def test_resumes_after_unpause(self):
        """Source should start collecting again when unpaused."""

        class CountingSource(SourcePlugin):
            collect_count = 0

            def probe(self):
                return ProbeResult(available=True, source="test", description="ok")

            def collect(self):
                self.collect_count += 1
                return [{"timestamp": "2026-01-01T00:00:00Z"}]

        class MockClient:
            def __init__(self):
                self.ingested = []
                self._tick = 0

            def is_paused(self):
                self._tick += 1
                # paused for first 2 ticks, unpaused for next 2, then exit
                if self._tick >= 5:
                    raise SystemExit(0)
                return self._tick <= 2

            def ingest(self, record):
                self.ingested.append(record)

        plugin = CountingSource()
        client = MockClient()

        import time as _time
        original_sleep = _time.sleep
        _time.sleep = lambda _: None
        try:
            try:
                plugin.start(client, {"interval_seconds": 1})
            except SystemExit:
                pass
        finally:
            _time.sleep = original_sleep

        assert plugin.collect_count == 2, f"Expected 2 collects (after unpause), got {plugin.collect_count}"
        assert len(client.ingested) == 2
