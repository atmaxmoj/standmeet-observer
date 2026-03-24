"""Tests for source runner — loading manifest, importing entrypoint, probing."""

import json
from pathlib import Path

import pytest

from source_framework.manifest import load_manifest
from source_framework.plugin import SourcePlugin, ProbeResult
from source_framework.runner import _import_plugin_class, load_and_probe


def _create_source_dir(tmp_path, manifest_data, plugin_code):
    """Helper to create a minimal source directory with manifest + plugin code."""
    # Write manifest
    (tmp_path / "manifest.json").write_text(json.dumps(manifest_data))

    # Write plugin module
    src_dir = tmp_path / "src" / "test_source"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text(plugin_code)

    return tmp_path


GOOD_PLUGIN_CODE = """
from source_framework.plugin import SourcePlugin, ProbeResult

class TestSource(SourcePlugin):
    def probe(self):
        return ProbeResult(available=True, source="test", description="ok")

    def collect(self):
        return [{"timestamp": "2026-01-01T00:00:00Z", "data": "hello"}]
"""

UNAVAILABLE_PLUGIN_CODE = """
from source_framework.plugin import SourcePlugin, ProbeResult

class UnavailableSource(SourcePlugin):
    def probe(self):
        return ProbeResult(available=False, source="test", description="not available")

    def collect(self):
        return []
"""


class TestImportPluginClass:
    def test_import_valid_entrypoint(self, tmp_path):
        source_dir = _create_source_dir(
            tmp_path,
            {"name": "test", "entrypoint": "test_source:TestSource"},
            GOOD_PLUGIN_CODE,
        )
        manifest = load_manifest(source_dir)
        cls = _import_plugin_class(manifest)
        assert issubclass(cls, SourcePlugin)
        assert cls.__name__ == "TestSource"

    def test_invalid_entrypoint_format(self, tmp_path):
        source_dir = _create_source_dir(
            tmp_path,
            {"name": "test", "entrypoint": "no_colon_here"},
            GOOD_PLUGIN_CODE,
        )
        manifest = load_manifest(source_dir)
        with pytest.raises(ValueError, match="Invalid entrypoint"):
            _import_plugin_class(manifest)

    def test_empty_entrypoint(self, tmp_path):
        source_dir = _create_source_dir(
            tmp_path,
            {"name": "test", "entrypoint": ""},
            GOOD_PLUGIN_CODE,
        )
        manifest = load_manifest(source_dir)
        with pytest.raises(ValueError, match="Invalid entrypoint"):
            _import_plugin_class(manifest)

    def test_nonexistent_module(self, tmp_path):
        source_dir = _create_source_dir(
            tmp_path,
            {"name": "test", "entrypoint": "nonexistent_module:Foo"},
            GOOD_PLUGIN_CODE,
        )
        manifest = load_manifest(source_dir)
        with pytest.raises(ModuleNotFoundError):
            _import_plugin_class(manifest)


class TestLoadAndProbe:
    def test_available_source(self, tmp_path):
        source_dir = _create_source_dir(
            tmp_path,
            {"name": "test", "entrypoint": "test_source:TestSource", "platform": ["darwin", "win32", "linux"]},
            GOOD_PLUGIN_CODE,
        )
        manifest, plugin = load_and_probe(source_dir)
        assert manifest.name == "test"
        assert plugin is not None
        assert plugin.probe().available

    def test_unavailable_source(self, tmp_path):
        # Use a unique module name to avoid sys.modules collision
        unavail_dir = tmp_path / "src" / "unavail_source"
        unavail_dir.mkdir(parents=True)
        (unavail_dir / "__init__.py").write_text(UNAVAILABLE_PLUGIN_CODE)
        (tmp_path / "manifest.json").write_text(json.dumps(
            {"name": "unavail", "entrypoint": "unavail_source:UnavailableSource", "platform": ["darwin", "win32", "linux"]}
        ))
        manifest, plugin = load_and_probe(tmp_path)
        assert manifest.name == "unavail"
        assert plugin is None

    def test_unsupported_platform(self, tmp_path):
        source_dir = _create_source_dir(
            tmp_path,
            {"name": "test", "entrypoint": "test_source:TestSource", "platform": ["nonexistent_os"]},
            GOOD_PLUGIN_CODE,
        )
        manifest, plugin = load_and_probe(source_dir)
        assert plugin is None


class TestRespawn:
    def test_respawns_after_crash(self, monkeypatch):
        """Source auto-restarts after run_source raises."""
        import source_framework.__main__ as main_mod

        call_count = 0

        def fake_run_source(source_dir, engine_url=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated crash")
            raise SystemExit(0)  # second+ call: clean exit

        monkeypatch.setattr(main_mod, "run_source", fake_run_source)
        monkeypatch.setattr(main_mod.time, "sleep", lambda _: None)
        monkeypatch.setattr("sys.argv", ["prog", "/fake/dir"])

        main_mod.main()  # returns normally after SystemExit breaks the loop

        assert call_count == 2, f"Expected 2 calls (crash + restart), got {call_count}"

    def test_clean_shutdown_no_respawn(self, monkeypatch):
        """SIGTERM/SIGINT causes clean exit, no respawn."""
        import source_framework.__main__ as main_mod

        call_count = 0

        def fake_run_source(source_dir, engine_url=None):
            nonlocal call_count
            call_count += 1
            raise SystemExit(0)

        monkeypatch.setattr(main_mod, "run_source", fake_run_source)
        monkeypatch.setattr(main_mod.time, "sleep", lambda _: None)
        monkeypatch.setattr("sys.argv", ["prog", "/fake/dir"])

        main_mod.main()  # returns normally

        assert call_count == 1, "Should not respawn after clean SystemExit"
