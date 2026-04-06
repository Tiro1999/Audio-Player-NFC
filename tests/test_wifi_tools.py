"""Tests for WiFi PSK hashing – verifiable against wpa_passphrase output."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools.wifi_tools import wpa_psk


def test_wpa_psk_known_vector():
    """Verify against a known WPA2 PSK (same output as wpa_passphrase)."""
    # wpa_passphrase "test" "12345678" → psk=…
    result = wpa_psk("test", "12345678")
    assert len(result) == 64, "PSK must be 64 hex chars (256 bit)"
    # This is the actual output of wpa_passphrase for SSID=test, pass=12345678
    assert result == "fe727aa8b64ac9b3f54c72432da14faed933ea511ecab15bbc6c52e7522f709a"


def test_psk_different_for_different_ssids():
    """Same password with different SSIDs must produce different hashes."""
    psk1 = wpa_psk("Network_A", "samepassword")
    psk2 = wpa_psk("Network_B", "samepassword")
    assert psk1 != psk2


def test_psk_deterministic():
    """Same inputs must always produce the same hash."""
    assert wpa_psk("MyWifi", "hunter2") == wpa_psk("MyWifi", "hunter2")
