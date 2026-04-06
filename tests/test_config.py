"""Tests for src.config – runnable on any machine (no Pi hardware needed)."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.config import Config


@pytest.fixture
def sample_config(tmp_path):
    data = {
        "wifi": [
            {"ssid": "TestNet", "psk": "pass123", "priority": 10},
        ],
        "bluetooth": {
            "speaker_mac": "AA:BB:CC:DD:EE:FF",
            "speaker_name": "Test Speaker",
        },
        "spotify": {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "http://localhost:8888/callback",
            "device_name": "Test-Box",
        },
        "nfc_tags": {
            "04A1B2C3": "spotify:playlist:abc123",
            "04D4E5F6": "spotify:album:xyz789",
        },
        "behavior": {
            "pause_on_remove": True,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_load_config(sample_config):
    cfg = Config(sample_config)
    assert cfg.speaker_mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.speaker_name == "Test Speaker"
    assert cfg.device_name == "Test-Box"
    assert cfg.client_id == "test_client_id"
    assert cfg.redirect_uri == "http://localhost:8888/callback"


def test_wifi_networks(sample_config):
    cfg = Config(sample_config)
    assert len(cfg.wifi_networks) == 1
    assert cfg.wifi_networks[0]["ssid"] == "TestNet"


def test_nfc_tags(sample_config):
    cfg = Config(sample_config)
    assert cfg.nfc_tags["04A1B2C3"] == "spotify:playlist:abc123"
    assert cfg.nfc_tags["04D4E5F6"] == "spotify:album:xyz789"


def test_pause_on_remove(sample_config):
    cfg = Config(sample_config)
    assert cfg.pause_on_remove is True


def test_pause_on_remove_default(tmp_path):
    """pause_on_remove defaults to False when not set."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"spotify": {}, "bluetooth": {}}))
    cfg = Config(str(path))
    assert cfg.pause_on_remove is False


def test_reload(sample_config):
    cfg = Config(sample_config)
    assert cfg.device_name == "Test-Box"

    # Modify file on disk
    with open(sample_config) as f:
        data = json.load(f)
    data["spotify"]["device_name"] = "Reloaded-Box"
    with open(sample_config, "w") as f:
        json.dump(data, f)

    cfg.reload()
    assert cfg.device_name == "Reloaded-Box"


def test_missing_config_raises():
    with pytest.raises(FileNotFoundError):
        Config("/nonexistent/path/config.json")
