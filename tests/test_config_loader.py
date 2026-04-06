"""Tests for src/config_loader.py."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.config_loader import load_config, _validate_config


# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_CONFIG = {
    "wifi": [{"ssid": "TestNet", "password": "secret", "priority": 10}],
    "spotify": {
        "client_id": "abc123",
        "client_secret": "xyz456",
        "redirect_uri": "http://localhost:8888/callback",
        "device_name": "NFC-Player",
    },
    "bluetooth": {
        "device_name": "My Speaker",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "reconnect_interval_seconds": 10,
    },
    "nfc": {
        "reader_type": "rc522",
        "tag_mappings": {
            "AABBCCDD": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        },
    },
}


def _write_config(data: dict) -> str:
    """Write *data* to a temporary JSON file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


# ── load_config ───────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_valid_config_from_explicit_path(self):
        path = _write_config(VALID_CONFIG)
        try:
            config = load_config(path)
            assert config["spotify"]["device_name"] == "NFC-Player"
            assert config["bluetooth"]["mac_address"] == "AA:BB:CC:DD:EE:FF"
        finally:
            os.unlink(path)

    def test_raises_file_not_found_when_no_config_exists(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_raises_value_error_for_invalid_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{ this is not valid json }")
        try:
            with pytest.raises(ValueError, match="not valid JSON"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_searches_default_paths_first_found(self, monkeypatch, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(VALID_CONFIG))

        import src.config_loader as cl
        monkeypatch.setattr(cl, "_DEFAULT_SEARCH_PATHS", [Path("/no/such/file.json"), cfg_file])
        config = load_config()
        assert config["wifi"][0]["ssid"] == "TestNet"


# ── _validate_config ──────────────────────────────────────────────────────────

class TestValidateConfig:
    def test_valid_config_passes(self):
        _validate_config(VALID_CONFIG)  # no exception

    def test_missing_wifi_section_raises(self):
        cfg = {k: v for k, v in VALID_CONFIG.items() if k != "wifi"}
        with pytest.raises(ValueError, match="wifi"):
            _validate_config(cfg)

    def test_empty_wifi_list_raises(self):
        cfg = {**VALID_CONFIG, "wifi": []}
        with pytest.raises(ValueError, match="non-empty list"):
            _validate_config(cfg)

    def test_missing_spotify_client_id_raises(self):
        cfg = {
            **VALID_CONFIG,
            "spotify": {**VALID_CONFIG["spotify"], "client_id": ""},
        }
        with pytest.raises(ValueError, match="spotify.client_id"):
            _validate_config(cfg)

    def test_missing_bluetooth_mac_raises(self):
        cfg = {
            **VALID_CONFIG,
            "bluetooth": {**VALID_CONFIG["bluetooth"], "mac_address": ""},
        }
        with pytest.raises(ValueError, match="bluetooth.mac_address"):
            _validate_config(cfg)

    @pytest.mark.parametrize("section", ["wifi", "spotify", "bluetooth", "nfc"])
    def test_missing_top_level_section_raises(self, section):
        cfg = {k: v for k, v in VALID_CONFIG.items() if k != section}
        with pytest.raises(ValueError, match=section):
            _validate_config(cfg)
