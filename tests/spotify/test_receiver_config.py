"""Tests for nfc_player.spotify.receiver_config (PyYAML only parses the output here)."""

import json
import logging
import os
import stat
from urllib.parse import urlsplit

import pytest
import yaml

from nfc_player.core import paths
from nfc_player.core.build_info import BuildInfo
from nfc_player.spotify import receiver_config
from nfc_player.spotify.receiver_config import main, render_receiver_config

# Appendix A: only these keys, go-librespot's schema has additionalProperties: false.
EXPECTED = {
    "device_name": "NFC-Box",
    "device_type": "speaker",
    "audio_backend": "pulseaudio",
    "bitrate": 160,
    "credentials": {"type": "zeroconf", "zeroconf": {"persist_credentials": True}},
    "server": {"enabled": True, "address": "127.0.0.1", "port": 3678},
}


@pytest.fixture
def maturities(monkeypatch):
    """main() sets up logging; record the maturity instead of changing the root logger."""
    calls = []
    monkeypatch.setattr(receiver_config, "setup_logging", calls.append)
    monkeypatch.setattr(receiver_config, "load_build_info", lambda: BuildInfo("v1.0.0", "release", ()))
    return calls


@pytest.fixture
def device(tmp_path, monkeypatch, maturities):
    """Temporary DEVICE_CONFIG and RECEIVER_DIR (0700, as provisioned)."""
    receiver_dir = tmp_path / "receiver"
    receiver_dir.mkdir(mode=0o700)
    monkeypatch.setattr(paths, "DEVICE_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(paths, "RECEIVER_DIR", receiver_dir)


def write_device_config(device_name):
    paths.DEVICE_CONFIG.write_text(json.dumps({"spotify": {"device_name": device_name}}), encoding="utf-8")


def rendered():
    return yaml.safe_load((paths.RECEIVER_DIR / "config.yml").read_text(encoding="utf-8"))


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


# --- render_receiver_config ---


def test_render_receiver_config_keys():
    assert yaml.safe_load(render_receiver_config("NFC-Box")) == EXPECTED


@pytest.mark.parametrize(
    "name",
    ["Kinderzimmer Box", "#1: Box", "true", "null", "~", "0x1F", "1e3", "- item", "{a}", "[x]", "*ref", "&a"]
    + ["!tag", "%TAG", "@home", "`x`", "|", ">", "Küche ♪", "  padded  ", "a" * 64],
)
def test_render_receiver_config_quotes_name(name):
    text = render_receiver_config(name)
    assert f'device_name: "{name}"\n' in text
    assert yaml.safe_load(text)["device_name"] == name


@pytest.mark.parametrize("name", ['Bad"Name', "back\\slash", "new\nline", "tab\there", "it's", "", "a" * 65])
def test_render_receiver_config_rejects_unsafe_name(name):
    with pytest.raises(ValueError):
        render_receiver_config(name)


def test_render_receiver_config_port():
    assert yaml.safe_load(render_receiver_config("NFC-Box", port=4000))["server"]["port"] == 4000


def test_default_server_matches_api_url():
    server = yaml.safe_load(render_receiver_config("NFC-Box"))["server"]
    api = urlsplit(paths.RECEIVER_API_URL)
    assert (server["address"], server["port"]) == (api.hostname, api.port)


# --- main ---


def test_receiver_config_main_writes_device_name(device, maturities):
    write_device_config("Kinderzimmer")
    assert main([]) == 0
    assert rendered() == {**EXPECTED, "device_name": "Kinderzimmer"}
    assert mode(paths.RECEIVER_DIR / "config.yml") == 0o600
    assert maturities == ["release"]


def test_receiver_config_main_uses_default_on_invalid_config(device, caplog):
    write_device_config('Bad"Name')
    assert main([]) == 0
    assert rendered()["device_name"] == "NFC-Box"
    assert any("NFC-Box" in message for message in warnings(caplog))


@pytest.mark.parametrize("broken", ["missing", "directory", "not json"])
def test_receiver_config_main_uses_default_without_device_config(device, caplog, broken):
    if broken == "directory":
        paths.DEVICE_CONFIG.mkdir()
    elif broken == "not json":
        paths.DEVICE_CONFIG.write_text("{", encoding="utf-8")
    assert main([]) == 0
    assert rendered()["device_name"] == "NFC-Box"
    assert any("NFC-Box" in message for message in warnings(caplog))


def test_receiver_config_main_keeps_other_files(device):
    receiver_dir = paths.RECEIVER_DIR
    (receiver_dir / "state.json").write_text('{"credentials": "keep"}', encoding="utf-8")
    (receiver_dir / "state.json").chmod(0o600)
    (receiver_dir / "lockfile").write_text("1234", encoding="utf-8")
    (receiver_dir / "config.yml").write_text("old: true\n", encoding="utf-8")
    (receiver_dir / "config.yml").chmod(0o644)
    write_device_config("Box")

    assert main([]) == 0

    assert sorted(path.name for path in receiver_dir.iterdir()) == ["config.yml", "lockfile", "state.json"]
    assert (receiver_dir / "state.json").read_text(encoding="utf-8") == '{"credentials": "keep"}'
    assert mode(receiver_dir / "state.json") == 0o600
    assert (receiver_dir / "lockfile").read_text(encoding="utf-8") == "1234"
    assert rendered()["device_name"] == "Box"
    assert mode(receiver_dir / "config.yml") == 0o600


def test_receiver_config_main_warns_about_config_yaml(device, caplog):
    (paths.RECEIVER_DIR / "config.yaml").write_text("device_name: Other\n", encoding="utf-8")
    write_device_config("Box")
    assert main([]) == 0
    assert any("config.yaml" in message for message in warnings(caplog))
    assert (paths.RECEIVER_DIR / "config.yaml").read_text(encoding="utf-8") == "device_name: Other\n"
    assert rendered()["device_name"] == "Box"


def test_receiver_config_main_no_warning_when_all_is_fine(device, caplog):
    write_device_config("Box")
    assert main([]) == 0
    assert warnings(caplog) == []


def test_receiver_config_main_write_failure_returns_1(tmp_path, monkeypatch, maturities, caplog):
    monkeypatch.setattr(paths, "DEVICE_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(paths, "RECEIVER_DIR", tmp_path / "not-provisioned")
    assert main([]) == 1
    assert any(r.levelno == logging.ERROR and "config.yml" in r.getMessage() for r in caplog.records)
    assert not (tmp_path / "not-provisioned").exists()
