"""Tests for src/spotify_controller.py."""

from unittest.mock import MagicMock, patch, call

import pytest

from src.spotify_controller import SpotifyController


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_controller(device_name="NFC-Player"):
    return SpotifyController(
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="http://localhost:8888/callback",
        device_name=device_name,
    )


def _inject_mock_client(controller: SpotifyController, mock_sp=None):
    """Replace the internal spotipy client with a MagicMock."""
    if mock_sp is None:
        mock_sp = MagicMock()
    controller._sp = mock_sp
    return mock_sp


def _device(name: str, device_id: str = "device-abc-123") -> dict:
    return {"name": name, "id": device_id}


# ── from_config ───────────────────────────────────────────────────────────────

class TestFromConfig:
    def test_constructs_from_valid_config(self):
        config = {
            "spotify": {
                "client_id": "cid",
                "client_secret": "csecret",
                "redirect_uri": "http://localhost:8888/callback",
                "device_name": "My Player",
            }
        }
        ctrl = SpotifyController.from_config(config)
        assert ctrl._client_id == "cid"
        assert ctrl._device_name == "My Player"

    def test_uses_default_redirect_uri_when_missing(self):
        config = {
            "spotify": {
                "client_id": "cid",
                "client_secret": "csecret",
                "device_name": "Player",
            }
        }
        ctrl = SpotifyController.from_config(config)
        assert ctrl._redirect_uri == "http://localhost:8888/callback"


# ── _find_device_id ───────────────────────────────────────────────────────────

class TestFindDeviceId:
    def test_returns_id_when_device_found(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {
            "devices": [_device("Other Device", "other-id"), _device("NFC-Player", "target-id")]
        }
        assert ctrl._find_device_id() == "target-id"

    def test_returns_none_when_device_not_found(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {"devices": [_device("Some Other Speaker")]}
        assert ctrl._find_device_id() is None

    def test_returns_none_on_api_error(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.devices.side_effect = Exception("API error")
        assert ctrl._find_device_id() is None

    def test_case_insensitive_device_name_match(self):
        ctrl = _make_controller("nfc-player")
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {"devices": [_device("NFC-Player", "id-123")]}
        assert ctrl._find_device_id() == "id-123"


# ── play ──────────────────────────────────────────────────────────────────────

class TestPlay:
    def _setup(self, device_name="NFC-Player"):
        ctrl = _make_controller(device_name)
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {"devices": [_device("NFC-Player", "dev-id")]}
        return ctrl, sp

    def test_plays_playlist_with_context_uri(self):
        ctrl, sp = self._setup()
        result = ctrl.play("spotify:playlist:abc123")
        assert result is True
        sp.start_playback.assert_called_once_with(
            device_id="dev-id", context_uri="spotify:playlist:abc123"
        )

    def test_plays_album_with_context_uri(self):
        ctrl, sp = self._setup()
        result = ctrl.play("spotify:album:xyz789")
        assert result is True
        sp.start_playback.assert_called_once_with(
            device_id="dev-id", context_uri="spotify:album:xyz789"
        )

    def test_plays_track_with_uris(self):
        ctrl, sp = self._setup()
        result = ctrl.play("spotify:track:TRACK_ID")
        assert result is True
        sp.start_playback.assert_called_once_with(
            device_id="dev-id", uris=["spotify:track:TRACK_ID"]
        )

    def test_returns_false_when_device_not_found(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {"devices": []}
        result = ctrl.play("spotify:playlist:abc123", retries=1, retry_delay=0)
        assert result is False
        sp.start_playback.assert_not_called()

    def test_retries_until_device_appears(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        # First call returns no devices; second call returns the device
        sp.devices.side_effect = [
            {"devices": []},
            {"devices": [_device("NFC-Player", "dev-id")]},
        ]
        result = ctrl.play("spotify:playlist:abc", retries=2, retry_delay=0)
        assert result is True
        assert sp.devices.call_count == 2

    def test_returns_false_on_playback_api_error(self):
        ctrl, sp = self._setup()
        sp.start_playback.side_effect = Exception("Playback error")
        result = ctrl.play("spotify:album:abc")
        assert result is False


# ── pause ─────────────────────────────────────────────────────────────────────

class TestPause:
    def test_pauses_when_device_found(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {"devices": [_device("NFC-Player", "dev-id")]}
        assert ctrl.pause() is True
        sp.pause_playback.assert_called_once_with(device_id="dev-id")

    def test_returns_false_when_device_not_found(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.devices.return_value = {"devices": []}
        assert ctrl.pause() is False


# ── is_playing ────────────────────────────────────────────────────────────────

class TestIsPlaying:
    def test_returns_true_when_device_playing(self):
        ctrl = _make_controller("NFC-Player")
        sp = _inject_mock_client(ctrl)
        sp.current_playback.return_value = {
            "is_playing": True,
            "device": {"name": "NFC-Player"},
        }
        assert ctrl.is_playing() is True

    def test_returns_false_when_different_device_playing(self):
        ctrl = _make_controller("NFC-Player")
        sp = _inject_mock_client(ctrl)
        sp.current_playback.return_value = {
            "is_playing": True,
            "device": {"name": "Phone Speaker"},
        }
        assert ctrl.is_playing() is False

    def test_returns_false_when_not_playing(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.current_playback.return_value = {"is_playing": False, "device": {"name": "NFC-Player"}}
        assert ctrl.is_playing() is False

    def test_returns_false_on_api_error(self):
        ctrl = _make_controller()
        sp = _inject_mock_client(ctrl)
        sp.current_playback.side_effect = Exception("Network error")
        assert ctrl.is_playing() is False
