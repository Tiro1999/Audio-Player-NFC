"""Tests for nfc_player.core.validate."""

import pytest

from nfc_player.core.validate import (
    PLACEHOLDER_MACS,
    device_name_error,
    is_psk_hash,
    normalize_mac,
    normalize_repo,
    normalize_uid,
    passphrase_error,
    speaker_name_error,
    ssid_error,
)

HEX64 = "0123456789abcdef" * 4


@pytest.mark.parametrize(
    ("ssid", "valid"),
    [
        ("", False),
        ("a" * 33, False),
        ("Café", True),
        ("a\tb", False),
        ("a", True),
        ("a" * 32, True),
        ("é" * 16, True),  # 32 bytes
        ("é" * 17, False),  # 17 characters, but 34 bytes
        ("a\x7fb", False),
        ("a:b", True),
        ("back\\slash", True),
        ("-x", True),
        ("\ud800", False),  # lone surrogate from a JSON escape
        (None, False),
    ],
)
def test_ssid_error_cases(ssid, valid):
    assert (ssid_error(ssid) is None) is valid


@pytest.mark.parametrize(
    ("secret", "security", "valid"),
    [
        ("12345678", "wpa-psk", True),
        ("1234567", "wpa-psk", False),
        (HEX64, "wpa-psk", True),
        ("pw\n", "sae", False),
        ("x", "open", False),
        ("a" * 63, "wpa-psk", True),
        ("g" * 64, "wpa-psk", False),  # 64 characters must be hex
        ("a" * 65, "wpa-psk", False),
        ("pass word", "wpa-psk", True),
        ("~" * 8, "wpa-psk", True),
        ("pässword", "wpa-psk", False),
        ("pass\tword", "wpa-psk", False),
        ("x", "sae", True),
        ("ä" * 128, "sae", True),
        ("a" * 129, "sae", False),
        ("", "sae", False),
        ("pw\ud800pw", "sae", False),
        ("", "open", True),
        ("12345678", "wep", False),
        (12345678, "wpa-psk", False),
    ],
)
def test_passphrase_error_cases(secret, security, valid):
    assert (passphrase_error(secret, security) is None) is valid


def test_passphrase_error_never_contains_the_secret():
    message = passphrase_error("geheim\n", "sae")
    assert message
    assert "geheim" not in message


@pytest.mark.parametrize(
    ("value", "expected"),
    [(HEX64, True), (HEX64.upper(), True), (HEX64 + "0", False), ("g" * 64, False), (None, False)],
)
def test_is_psk_hash(value, expected):
    assert is_psk_hash(value) is expected


def test_normalize_mac():
    assert normalize_mac("11:22:33:aa:bb:cc") == "11:22:33:AA:BB:CC"
    # A placeholder still normalizes; the caller decides what to do with it.
    assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aa:bb:cc:dd:ee:ff") in PLACEHOLDER_MACS


@pytest.mark.parametrize(
    "mac",
    [
        "",
        "AA:BB:CC:DD:EE",
        "AA-BB-CC-DD-EE-FF",
        "AABBCCDDEEFF",
        "GG:BB:CC:DD:EE:FF",
        "AA:BB:CC:DD:EE:FF\n",
        " AA:BB:CC:DD:EE:FF",
        "aa:bb:cc:dd:ee:ﬀ",  # ligature "ff" upper-cases to ASCII "FF"
        None,
    ],
)
def test_normalize_mac_rejects(mac):
    with pytest.raises(ValueError):
        normalize_mac(mac)


def test_normalize_uid():
    assert normalize_uid("04:a1-b2 c3") == "04A1B2C3"
    with pytest.raises(ValueError):
        normalize_uid("zz")


@pytest.mark.parametrize(
    ("uid", "expected"),
    [("04a1b2c3", "04A1B2C3"), ("04:A1:B2:C3:D4:E5:F6", "04A1B2C3D4E5F6"), ("0" * 20, "0" * 20)],
)
def test_normalize_uid_accepts(uid, expected):
    assert normalize_uid(uid) == expected


@pytest.mark.parametrize("uid", ["04A1B2C", "0" * 21, "04A1B2C3\t", "04_A1_B2_C3", "", None])
def test_normalize_uid_rejects(uid):
    with pytest.raises(ValueError):
        normalize_uid(uid)


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("NFC-Box", True),
        ("Wohnzimmer Box", True),
        ("Küche", True),
        ("a", True),
        ("x" * 64, True),
        ("", False),
        ("x" * 65, False),
        ('Say "hi"', False),
        ("it's", False),
        ("back\\slash", False),
        ("line\nbreak", False),
        ("tab\there", False),
        (None, False),
    ],
)
def test_device_name_error_cases(name, valid):
    assert (device_name_error(name) is None) is valid


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("JBL Flip 5", True),
        ("Küche", True),
        ('Tim\'s "Box"', True),
        ("x" * 64, True),
        ("", False),
        ("x" * 65, False),
        ("line\nbreak", False),
        ("tab\tname", False),
        ("del\x7f", False),
        (None, False),
    ],
)
def test_speaker_name_error_cases(name, valid):
    assert (speaker_name_error(name) is None) is valid


# The 7 formats of tests/test_updater.py::TestNormalizeRepo, with a neutral owner.
@pytest.mark.parametrize(
    "repo",
    [
        "Owner-1/Audio-Player-NFC",
        "https://github.com/Owner-1/Audio-Player-NFC",
        "https://github.com/Owner-1/Audio-Player-NFC.git",
        "https://github.com/Owner-1/Audio-Player-NFC/",
        "git@github.com:Owner-1/Audio-Player-NFC.git",
        "  Owner-1/Audio-Player-NFC  ",
        "http://github.com/Owner-1/Audio-Player-NFC",
    ],
)
def test_normalize_repo_accepts_old_formats(repo):
    assert normalize_repo(repo) == "Owner-1/Audio-Player-NFC"


def test_normalize_repo_prefix_ignores_case():
    assert normalize_repo("HTTPS://GitHub.com/owner/repo") == "owner/repo"


@pytest.mark.parametrize(
    "repo",
    [
        "bad",
        "",
        "owner/repo/extra",
        "../repo",
        "owner/..",
        "owner/re po",
        "https://user:token@github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        None,
    ],
)
def test_normalize_repo_rejects(repo):
    with pytest.raises(ValueError):
        normalize_repo(repo)
