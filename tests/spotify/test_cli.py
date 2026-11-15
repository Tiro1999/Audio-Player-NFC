"""Tests for nfc_player.spotify.cli (nfc-test)."""

import json
import logging

import pytest

from nfc_player.core import paths
from nfc_player.core.build_info import BuildInfo
from nfc_player.spotify import cli
from nfc_player.spotify.receiver import ReceiverError, ReceiverNotReady


class FakeReceiver:
    """Stands in for Receiver: records its device name and the played URIs."""

    error: ReceiverError | None = None
    instances: list["FakeReceiver"] = []

    def __init__(self, *, device_name: str) -> None:
        self.device_name = device_name
        self.played: list[str] = []
        FakeReceiver.instances.append(self)

    def play(self, uri: str) -> None:
        self.played.append(uri)
        if self.error is not None:
            raise self.error


@pytest.fixture(autouse=True)
def fake_receiver(tmp_path, monkeypatch):
    monkeypatch.setattr(FakeReceiver, "error", None)
    monkeypatch.setattr(FakeReceiver, "instances", [])
    monkeypatch.setattr(cli, "Receiver", FakeReceiver)
    monkeypatch.setattr(cli, "setup_logging", lambda maturity: None)
    monkeypatch.setattr(cli, "load_build_info", lambda: BuildInfo("v1.0.0", "release", ("spotify",)))
    monkeypatch.setattr(paths, "DEVICE_CONFIG", tmp_path / "config.json")


def write_device_config(device_name):
    paths.DEVICE_CONFIG.write_text(json.dumps({"spotify": {"device_name": device_name}}), encoding="utf-8")


def test_cli_invalid_uri_returns_1(capsys):
    assert cli.main(["https://evil.com/track/x"]) == 1
    err = capsys.readouterr().err
    assert "'https://evil.com/track/x'" in err
    assert "spotify:track:" in err
    assert "https://open.spotify.com/" in err
    assert FakeReceiver.instances == []


def test_cli_play_success_returns_0(caplog):
    caplog.set_level(logging.INFO, logger="nfc_player.spotify")
    write_device_config("Kinderzimmer")
    assert cli.main(["https://open.spotify.com/intl-de/album/abc123?si=x"]) == 0
    [receiver] = FakeReceiver.instances
    assert receiver.played == ["spotify:album:abc123"]
    assert receiver.device_name == "Kinderzimmer"
    assert "spotify:album:abc123" in caplog.text


def test_cli_without_device_config_uses_default_name():
    assert cli.main(["spotify:track:abc"]) == 0
    assert FakeReceiver.instances[0].device_name == "NFC-Box"


@pytest.mark.parametrize(
    "error",
    [
        ReceiverError("the receiver is not reachable: [Errno 111] Connection refused"),
        ReceiverNotReady("no Spotify session yet: select 'Box' once in the Spotify app"),
    ],
)
def test_cli_receiver_error_returns_1(caplog, error):
    FakeReceiver.error = error
    assert cli.main(["spotify:track:abc"]) == 1
    assert any(r.levelno == logging.ERROR and str(error) in r.getMessage() for r in caplog.records)


def test_cli_missing_argument_exits_2(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main([])
    assert raised.value.code == 2
