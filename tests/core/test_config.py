"""Tests for nfc_player.core.config."""

import json
import os
import stat

import pytest

from nfc_player.core.config import (
    Config,
    ConfigError,
    Speaker,
    WifiSeed,
    load_config,
    parse_config,
    read_raw,
    remove_speaker,
    remove_wifi_seed,
    scrub_secrets,
    to_device_dict,
    upsert_speaker,
    write_json_atomic,
    write_text_atomic,
)

PSK_HASH = "0123456789abcdef" * 4
MAC_A = "11:22:33:44:55:AA"
MAC_B = "11:22:33:44:55:BB"

FULL_RAW = {
    "wifi": [
        {"ssid": "Home", "psk": "password-home", "priority": 10},
        {"ssid": "Office", "psk_hash": PSK_HASH},
        {"ssid": "Cafe", "security": "open", "hidden": True},
    ],
    "bluetooth": {"speaker_mac": MAC_A},
    "spotify": {"device_name": "Box", "client_id": "cid", "client_secret": "client-secret-x"},
    "nfc_tags": {"04a1b2c3": "spotify:album:x"},
    "behavior": {"pause_on_remove": True},
    "update": {"auto_update": True, "github_repo": "owner/repo", "token": "ghp_token123"},
}


def write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def sample_config(tmp_path):
    """The sample of the old tests, with non-placeholder MACs and a valid password."""
    return write_config(
        tmp_path,
        {
            "wifi": [{"ssid": "TestNet", "psk": "pass1234", "priority": 10}],
            "bluetooth": {
                "speakers": [
                    {"mac": MAC_B, "name": "Speaker B", "priority": 5},
                    {"mac": MAC_A, "name": "Speaker A", "priority": 10},
                ]
            },
            "spotify": {"device_name": "Test-Box"},
            "nfc_tags": {"04A1B2C3": "spotify:playlist:abc123", "04D4E5F6": "spotify:album:xyz789"},
            "behavior": {"pause_on_remove": True},
        },
    )


# --- Ported from tests/test_config.py ---


def test_load_config(sample_config):
    cfg = load_config(sample_config)
    assert cfg.speakers[0] == Speaker(MAC_A, "Speaker A", 10)
    assert cfg.device_name == "Test-Box"
    assert cfg.wifi == (WifiSeed("TestNet", 10, "pass1234", "wpa-psk"),)
    assert cfg.warnings == ()


def test_speakers_sorted_by_priority(sample_config):
    assert [s.mac for s in load_config(sample_config).speakers] == [MAC_A, MAC_B]


def test_nfc_tags(sample_config):
    assert load_config(sample_config).nfc_tags == {
        "04A1B2C3": "spotify:playlist:abc123",
        "04D4E5F6": "spotify:album:xyz789",
    }


def test_pause_on_remove(sample_config):
    assert load_config(sample_config).pause_on_remove is True


def test_pause_on_remove_default():
    assert parse_config({"spotify": {}, "bluetooth": {}}).pause_on_remove is False


def test_defaults():
    cfg = parse_config({})
    assert cfg.wifi == ()
    assert cfg.speakers == ()
    assert cfg.device_name == "NFC-Box"
    assert cfg.nfc_tags == {}
    assert cfg.pause_on_remove is False
    assert cfg.wifi_tags is True
    assert cfg.auto_update is False
    assert cfg.github_repo == ""
    assert cfg.update_token is None
    assert cfg.warnings == ()


def test_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.json")


# --- Files edited on Windows (Review Focus 3) ---


def test_load_config_accepts_bom_and_crlf(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b'\xef\xbb\xbf{\r\n "behavior": {"pause_on_remove": true}\r\n}')
    assert load_config(path).pause_on_remove is True


def test_read_raw_trailing_comma_is_config_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{\n  "behavior": {"pause_on_remove": true},\n}\n', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        read_raw(path)
    assert "line" in excinfo.value.problems[0]


def test_read_raw_rejects_non_utf8(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes('{"spotify": {"device_name": "Küche"}}'.encode("latin-1"))
    with pytest.raises(ConfigError):
        read_raw(path)


def test_read_raw_requires_object(tmp_path):
    with pytest.raises(ConfigError):
        read_raw(write_config(tmp_path, ["wifi"]))


def test_read_raw_error_does_not_echo_content(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"wifi": [{"ssid": "Home", "psk": "geheim-123"}] oops}', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        read_raw(path)
    assert "geheim-123" not in str(excinfo.value)


def test_parse_config_collects_all_problems():
    with pytest.raises(ConfigError) as excinfo:
        parse_config({"wifi": {}, "behavior": {"pause_on_remove": "false"}})
    problems = excinfo.value.problems
    assert len(problems) == 2
    assert any("wifi" in problem for problem in problems)
    assert any("behavior.pause_on_remove" in problem for problem in problems)


def test_quoted_numbers_and_flags_are_errors():
    raw = {
        "wifi": [{"ssid": "Home", "psk": "password1", "priority": "10", "hidden": "false"}],
        "bluetooth": {"speakers": [{"mac": MAC_A, "priority": "10"}]},
    }
    with pytest.raises(ConfigError) as excinfo:
        parse_config(raw)
    assert len(excinfo.value.problems) == 3


def test_parse_config_requires_object():
    with pytest.raises(ConfigError):
        parse_config(["wifi"])


@pytest.mark.parametrize(
    "raw",
    [
        {"bluetooth": []},
        {"bluetooth": {"speakers": {}}},
        {"spotify": "NFC-Box"},
        {"behavior": None},
        {"update": []},
        {"nfc_tags": []},
        {"update": {"auto_update": "yes"}},
        {"behavior": {"wifi_tags": 1}},
        {"behavior": {"volume": 50}},
        {"spotify": {"device_name": 'Say "hi"'}},
        {"spotify": {"device_name": ""}},
        {"wifi": [{"ssid": "Home", "priority": True}]},
        {"bluetooth": {"speakers": [{"mac": MAC_A, "priority": 1.5}]}},
    ],
)
def test_parse_config_errors(raw):
    with pytest.raises(ConfigError):
        parse_config(raw)


# --- WiFi seeds ---


def test_wifi_seed_secret_prefers_psk_hash():
    cfg = parse_config({"wifi": [{"ssid": "Home", "psk": "password1", "psk_hash": PSK_HASH}]})
    assert cfg.wifi == (WifiSeed("Home", 5, PSK_HASH, "wpa-psk"),)


def test_wifi_seed_without_secret_is_priority_only():
    cfg = parse_config({"wifi": [{"ssid": "Home", "priority": 20}]})
    assert cfg.wifi == (WifiSeed("Home", 20, None, None),)
    assert cfg.wifi[0].security is None


@pytest.mark.parametrize(
    ("entry", "secret", "security"),
    [
        ({"ssid": "A", "psk": "password1"}, "password1", "wpa-psk"),
        ({"ssid": "A", "psk": "pw", "security": "sae"}, "pw", "sae"),
        ({"ssid": "A", "security": "open"}, None, "open"),
        ({"ssid": "A", "psk": "", "psk_hash": ""}, None, None),
        # An entry whose secret was already scrubbed only carries its priority.
        ({"ssid": "A", "security": "sae"}, None, None),
    ],
)
def test_wifi_seed_security(entry, secret, security):
    seed = parse_config({"wifi": [entry]}).wifi[0]
    assert (seed.secret, seed.security) == (secret, security)


def test_wifi_seed_hidden_and_priority_bounds():
    cfg = parse_config(
        {"wifi": [{"ssid": "Low", "priority": -999, "hidden": True}, {"ssid": "High", "priority": 999}]}
    )
    assert cfg.wifi == (WifiSeed("Low", -999, hidden=True), WifiSeed("High", 999))


@pytest.mark.parametrize(
    "entry",
    [
        "Home",
        {"psk": "password1"},
        {"ssid": "", "psk": "password1"},
        {"ssid": "x" * 33},
        {"ssid": "Home", "psk": "pw-7chr"},
        {"ssid": "Home", "psk": 12345678},
        {"ssid": "Home", "psk_hash": "pw-7chr"},
        {"ssid": "Home", "psk": "pw-7chr-but-open", "security": "open"},
        {"ssid": "Home", "psk": "password1", "security": "wpa2"},
        {"ssid": "Home", "psk_hash": PSK_HASH, "security": "sae"},
        {"ssid": "Home", "priority": 1000},
    ],
)
def test_invalid_wifi_entry_skipped_with_warning(entry):
    cfg = parse_config({"wifi": [entry, {"ssid": "Valid"}]})
    assert [seed.ssid for seed in cfg.wifi] == ["Valid"]
    assert len(cfg.warnings) == 1
    assert "pw-7chr" not in cfg.warnings[0]


# --- Speakers ---


def test_legacy_single_speaker_priority_10():
    cfg = parse_config({"bluetooth": {"speaker_mac": "11:22:33:44:55:aa", "speaker_name": "Legacy Speaker"}})
    assert cfg.speakers == (Speaker(MAC_A, "Legacy Speaker", 10),)
    unnamed = parse_config({"bluetooth": {"speaker_mac": MAC_A}})
    assert unnamed.speakers == (Speaker(MAC_A, MAC_A, 10),)


def test_speakers_sorted_and_placeholders_skipped():
    cfg = parse_config(
        {
            "bluetooth": {
                "speakers": [
                    {"mac": "11:22:33:44:55:01", "name": "Low", "priority": 1},
                    {"mac": "aa:bb:cc:dd:ee:ff", "name": "Placeholder", "priority": 10},
                    {"mac": "11:22:33:44:55:02", "name": "High", "priority": 9},
                    {"mac": "11:22:33:44:55:03", "name": "Also low", "priority": 1},
                    {"mac": "00:00:00:00:00:00", "name": "Zero", "priority": 5},
                    {"mac": "bad", "name": "Bad", "priority": 5},
                    {"mac": "11:22:33:44:55:04", "name": "Too high", "priority": 11},
                    {"mac": "11:22:33:44:55:05", "name": "Negative", "priority": -1},
                ]
            }
        }
    )
    assert [s.name for s in cfg.speakers] == ["High", "Low", "Also low"]
    assert len(cfg.warnings) == 5


def test_speaker_defaults():
    cfg = parse_config({"bluetooth": {"speakers": [{"mac": MAC_A}]}})
    assert cfg.speakers == (Speaker(MAC_A, MAC_A, 0),)


def test_speakers_list_wins_over_legacy_keys():
    cfg = parse_config({"bluetooth": {"speakers": [{"mac": MAC_A, "priority": 3}], "speaker_mac": MAC_B}})
    assert [s.mac for s in cfg.speakers] == [MAC_A]


@pytest.mark.parametrize("name", ["line\nbreak", "tab\tname", "x" * 65, 5])
def test_invalid_speaker_name_skipped_with_warning(name):
    speakers = [{"mac": MAC_A, "name": name}, {"mac": MAC_B, "name": "Ok"}]
    cfg = parse_config({"bluetooth": {"speakers": speakers}})
    assert [s.mac for s in cfg.speakers] == [MAC_B]
    assert len(cfg.warnings) == 1


# --- Other sections ---


def test_web_api_keys_ignored_with_warning():
    cfg = parse_config(
        {
            "spotify": {
                "client_id": "my-client-id",
                "client_secret": "my-client-secret",
                "redirect_uri": "http://127.0.0.1:8888/callback",
                "device_name": "Box",
            }
        }
    )
    assert cfg.device_name == "Box"
    assert len(cfg.warnings) == 1
    for key in ("client_id", "client_secret", "redirect_uri"):
        assert key in cfg.warnings[0]
    assert "my-client-secret" not in cfg.warnings[0]


def test_nfc_tags_keys_normalized():
    cfg = parse_config(
        {"nfc_tags": {"04:a1:b2:c3": "spotify:album:x", "zz": "spotify:album:y", "04D4E5F6": 7}}
    )
    assert cfg.nfc_tags == {"04A1B2C3": "spotify:album:x"}
    assert len(cfg.warnings) == 2


def test_nfc_tags_duplicate_uid_warns():
    cfg = parse_config({"nfc_tags": {"04:A1:B2:C3": "spotify:album:x", "04a1b2c3": "spotify:album:y"}})
    assert cfg.nfc_tags == {"04A1B2C3": "spotify:album:y"}
    assert len(cfg.warnings) == 1
    assert "04A1B2C3" in cfg.warnings[0]


def test_github_repo_normalized():
    cfg = parse_config({"update": {"auto_update": True, "github_repo": "https://github.com/owner/repo.git"}})
    assert (cfg.auto_update, cfg.github_repo) == (True, "owner/repo")


def test_invalid_github_repo_becomes_empty_with_warning():
    cfg = parse_config({"update": {"github_repo": "https://user:ghp_leak@github.com/owner/repo"}})
    assert cfg.github_repo == ""
    assert len(cfg.warnings) == 1
    assert "ghp_leak" not in cfg.warnings[0]


def test_update_token():
    assert parse_config({"update": {"token": " ghp_abc123\n"}}).update_token == "ghp_abc123"
    assert parse_config({"update": {"token": ""}}).update_token is None
    bad = parse_config({"update": {"token": "ghp abc"}})
    assert bad.update_token is None
    assert len(bad.warnings) == 1
    assert "ghp abc" not in bad.warnings[0]


def test_reprs_hide_secrets():
    assert "password1" not in repr(WifiSeed("Home", secret="password1"))
    assert "ghp_abc123" not in repr(Config(update_token="ghp_abc123"))


# --- Device copy and secret scrubbing ---


def test_to_device_dict_has_no_secrets():
    device = to_device_dict(parse_config(FULL_RAW))
    assert device == {
        "wifi": [
            {"ssid": "Home", "priority": 10, "hidden": False},
            {"ssid": "Office", "priority": 5, "hidden": False},
            {"ssid": "Cafe", "priority": 5, "hidden": True, "security": "open"},
        ],
        "bluetooth": {"speakers": [{"mac": MAC_A, "name": MAC_A, "priority": 10}]},
        "spotify": {"device_name": "Box"},
        "nfc_tags": {"04A1B2C3": "spotify:album:x"},
        "behavior": {"pause_on_remove": True, "wifi_tags": True},
        "update": {"auto_update": True, "github_repo": "owner/repo"},
    }
    text = json.dumps(device)
    for secret in ("password-home", PSK_HASH, "client-secret-x", "ghp_token123"):
        assert secret not in text


def test_device_dict_reloads_unchanged():
    device = to_device_dict(parse_config(FULL_RAW))
    reloaded = parse_config(device)
    assert reloaded.warnings == ()
    assert to_device_dict(reloaded) == device


def test_scrub_secrets_removes_and_reports():
    raw = {
        "wifi": [
            {"ssid": "Home", "psk": "password-home", "priority": 10},
            {"ssid": "Office", "psk_hash": PSK_HASH},
            {"ssid": "Cafe"},
        ],
        "spotify": {"device_name": "Box", "client_id": "cid", "client_secret": "client-secret-x"},
        "update": {"auto_update": True, "token": "ghp_token123"},
    }
    scrubbed, removed = scrub_secrets(raw, imported_wifi=("Home", "Office"), token_saved=True)
    assert sorted(removed) == sorted(
        ["wifi[Home].psk", "wifi[Office].psk_hash", "update.token", "spotify.client_secret"]
    )
    assert scrubbed == {
        "wifi": [{"ssid": "Home", "priority": 10}, {"ssid": "Office"}, {"ssid": "Cafe"}],
        "spotify": {"device_name": "Box", "client_id": "cid"},
        "update": {"auto_update": True},
    }
    assert raw["wifi"][0]["psk"] == "password-home"


def test_scrub_secrets_keeps_wifi_not_imported():
    raw = {
        "wifi": [
            {"ssid": "Home", "psk": "password-home"},
            {"ssid": "home", "psk": "other-case"},  # SSIDs match exactly
            {"ssid": "Office", "psk": "password-office"},  # failed in NetworkManager
            {"ssid": "Bad", "psk": "pw-7chr"},  # skipped by parse_config
            {"psk": "no-ssid"},
            {"ssid": 5, "psk": "number-ssid"},
        ]
    }
    scrubbed, removed = scrub_secrets(raw, imported_wifi=("Home",))
    assert scrubbed["wifi"] == [{"ssid": "Home"}, *raw["wifi"][1:]]
    assert removed == ["wifi[Home].psk"]


def test_scrub_secrets_keeps_token_unless_saved():
    raw = {"spotify": {"client_secret": "client-secret-x"}, "update": {"token": "ghp_token123"}}
    scrubbed, removed = scrub_secrets(raw)
    assert scrubbed == {"spotify": {}, "update": {"token": "ghp_token123"}}
    assert removed == ["spotify.client_secret"]


def test_scrub_secrets_without_secrets_changes_nothing():
    raw = {"wifi": [{"ssid": "Home"}], "update": {"auto_update": False}}
    assert scrub_secrets(raw) == (raw, [])


# --- Raw edits for the CLIs ---


def test_upsert_speaker_migrates_legacy():
    raw = {"bluetooth": {"speaker_mac": MAC_A, "speaker_name": "Old"}, "spotify": {"device_name": "Box"}}
    result = upsert_speaker(raw, Speaker(MAC_B, "New", 5))
    assert result == {
        "bluetooth": {
            "speakers": [
                {"mac": MAC_A, "name": "Old", "priority": 10},
                {"mac": MAC_B, "name": "New", "priority": 5},
            ]
        },
        "spotify": {"device_name": "Box"},
    }
    assert raw["bluetooth"] == {"speaker_mac": MAC_A, "speaker_name": "Old"}


def test_upsert_speaker_migration_uppercases_legacy_mac():
    new = Speaker(MAC_B, "New", 5)
    named = upsert_speaker({"bluetooth": {"speaker_mac": MAC_A.lower(), "speaker_name": "Old"}}, new)
    assert named["bluetooth"]["speakers"][0] == {"mac": MAC_A, "name": "Old", "priority": 10}
    unnamed = upsert_speaker({"bluetooth": {"speaker_mac": MAC_A.lower()}}, new)
    assert unnamed["bluetooth"]["speakers"][0] == {"mac": MAC_A, "name": MAC_A, "priority": 10}
    invalid = upsert_speaker({"bluetooth": {"speaker_mac": "bad"}}, new)
    assert invalid["bluetooth"]["speakers"][0] == {"mac": "bad", "name": "bad", "priority": 10}


def test_upsert_speaker_updates_existing_entry():
    raw = {
        "bluetooth": {"speakers": [{"mac": MAC_A.lower(), "name": "Old", "priority": 1, "note": "kitchen"}]}
    }
    result = upsert_speaker(raw, Speaker(MAC_A, "New", 7))
    assert result["bluetooth"]["speakers"] == [
        {"mac": MAC_A, "name": "New", "priority": 7, "note": "kitchen"}
    ]


def test_upsert_speaker_creates_section():
    result = upsert_speaker({}, Speaker(MAC_A, "A", 5))
    assert result == {"bluetooth": {"speakers": [{"mac": MAC_A, "name": "A", "priority": 5}]}}


def test_upsert_speaker_rejects_broken_section():
    with pytest.raises(ConfigError):
        upsert_speaker({"bluetooth": {"speakers": {}}}, Speaker(MAC_A, "A", 5))


def test_remove_speaker_without_section():
    raw = {"spotify": {"device_name": "Box"}}
    assert remove_speaker(raw, MAC_A) == (raw, False)


def test_remove_speaker():
    raw = {
        "bluetooth": {
            "speakers": [
                {"mac": MAC_A, "name": "A", "priority": 1},
                {"mac": MAC_B.lower(), "name": "B", "priority": 2},
            ]
        }
    }
    result, removed = remove_speaker(raw, MAC_B)
    assert removed is True
    assert result["bluetooth"]["speakers"] == [{"mac": MAC_A, "name": "A", "priority": 1}]
    assert remove_speaker(result, MAC_B) == (result, False)


def test_remove_legacy_speaker():
    raw = {"bluetooth": {"speaker_mac": MAC_A, "speaker_name": "Old", "other": 1}}
    assert remove_speaker(raw, MAC_A.lower()) == ({"bluetooth": {"other": 1}}, True)


def test_remove_wifi_seed():
    raw = {"wifi": [{"ssid": "Home", "priority": 10}, {"ssid": "home"}, {"ssid": "Office"}]}
    result, removed = remove_wifi_seed(raw, "Home")
    assert removed is True
    assert result["wifi"] == [{"ssid": "home"}, {"ssid": "Office"}]
    assert remove_wifi_seed({"spotify": {}}, "Home") == ({"spotify": {}}, False)


# --- Atomic writes (Review Focus 5) ---


def test_write_json_atomic_keeps_old_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    def power_loss(src, dst):
        raise OSError("simulated power loss")

    monkeypatch.setattr(os, "replace", power_loss)
    with pytest.raises(OSError, match="simulated power loss"):
        write_json_atomic(path, {"new": True})
    assert path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_write_text_atomic_cleans_up_when_writing_fails(tmp_path):
    path = tmp_path / "token"
    path.write_text("old\n", encoding="utf-8")
    with pytest.raises(UnicodeEncodeError):
        write_text_atomic(path, "\ud800")
    assert path.read_text(encoding="utf-8") == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["token"]


def test_write_json_atomic_format_and_default_mode(tmp_path):
    path = tmp_path / "device.json"
    write_json_atomic(path, {"name": "Café", "list": [1]})
    assert path.read_bytes() == '{\n  "name": "Café",\n  "list": [\n    1\n  ]\n}\n'.encode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_write_text_atomic_replaces_content_and_mode(tmp_path):
    path = tmp_path / "token"
    path.write_text("old\n", encoding="utf-8")
    path.chmod(0o644)
    write_text_atomic(path, "new\n", mode=0o600)
    assert path.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["token"]


def test_write_text_atomic_applies_owner(tmp_path):
    other = next((gid for gid in os.getgroups() if gid != os.getgid()), None)
    if other is None:
        pytest.skip("needs a user with a second group")
    path = tmp_path / "device.json"
    write_text_atomic(path, "{}\n", mode=0o640, owner=(os.getuid(), other))
    assert path.stat().st_gid == other
