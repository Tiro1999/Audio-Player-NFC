"""Tests for nfc_player.spotify.uri."""

from types import SimpleNamespace

import ndef
import pytest

from nfc_player.spotify.uri import SPOTIFY_TYPES, spotify_uri_from_record, to_spotify_uri

TYPES = ("track", "album", "playlist", "artist", "episode", "show", "audiobook", "chapter")


def test_spotify_types():
    assert SPOTIFY_TYPES == TYPES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        *[(f"spotify:{kind}:abc123", f"spotify:{kind}:abc123") for kind in TYPES],
        *[(f"https://open.spotify.com/{kind}/abc123", f"spotify:{kind}:abc123") for kind in TYPES],
        ("https://open.spotify.com/intl-de/track/abc123", "spotify:track:abc123"),
        ("HTTPS://OPEN.SPOTIFY.COM/track/x", "spotify:track:x"),
    ],
)
def test_to_spotify_uri_valid(text, expected):
    assert to_spotify_uri(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.com/track/x",
        "https://open.spotify.com.evil.tld/track/x",
        "https://user@evil.com/open.spotify.com/track/x",
        "spotify:foo:x",
        "",
    ],
)
def test_to_spotify_uri_rejects(text):
    assert to_spotify_uri(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://open.spotify.com/intl-pt-br/album/abc", "spotify:album:abc"),
        ("https://open.spotify.com/track/abc?si=0123abcd&context=x", "spotify:track:abc"),
        ("https://open.spotify.com/track/abc#frag", "spotify:track:abc"),
        ("https://open.spotify.com:443/track/abc", "spotify:track:abc"),
        ("http://open.spotify.com:80/track/abc", "spotify:track:abc"),
        ("https://open.spotify.com:/track/abc", "spotify:track:abc"),
        ("spotify:track:" + "a" * 64, "spotify:track:" + "a" * 64),
        # Hand-written tags and config values: surrounding whitespace is dropped.
        ("  spotify:track:abc\n", "spotify:track:abc"),
        ("\thttps://open.spotify.com/show/abc \r\n", "spotify:show:abc"),
    ],
)
def test_to_spotify_uri_url_variants(text, expected):
    assert to_spotify_uri(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Other hosts and userinfo tricks
        "https://user@open.spotify.com/track/x",
        "https://open.spotify.com@evil.com/track/x",
        "https://open.spotify.com:443@evil.com/track/x",
        "https://open.spotify.com\\@evil.com/track/x",
        "https://open.spotify.com./track/x",
        "https://[open.spotify.com]/track/x",
        "https://spotify.com/track/x",
        "//open.spotify.com/track/x",
        "open.spotify.com/track/x",
        # Ports and schemes
        "https://open.spotify.com:8080/track/x",
        "https://open.spotify.com:abc/track/x",
        "ftp://open.spotify.com/track/x",
        "spotify://track/x",
        # Paths
        "https://open.spotify.com/track/",
        "https://open.spotify.com/track/x/",
        "https://open.spotify.com/track/x/extra",
        "https://open.spotify.com//track/x",
        "https://open.spotify.com/TRACK/x",
        "https://open.spotify.com/user/x",
        "https://open.spotify.com/embed/track/x",
        "https://open.spotify.com/intl-deu/track/x",
        "https://open.spotify.com/intl-/track/x",
        "https://open.spotify.com/intl-de/intl-de/track/x",
        "https://open.spotify.com/track/abc-def",
        "https://open.spotify.com/track/" + "a" * 65,
        # Control characters that urlsplit would silently drop
        "https://open.spot\tify.com/track/x",
        "https://open.spotify.com/tr\nack/x",
        "spotify:track:abc\x00",
        # Native URIs
        "spotify:track:",
        "spotify:track:" + "a" * 65,
        "spotify:track:abc def",
        "spotify:track:abc:extra",
        "spotify:TRACK:abc",
        "SPOTIFY:track:abc",
        "spotify:user:someone:playlist:abc",
        "spotify:track:١٢",  # non-ASCII digits
    ],
)
def test_to_spotify_uri_rejects_tricks(text):
    assert to_spotify_uri(text) is None


@pytest.mark.parametrize("value", [None, b"spotify:track:abc", 42, ["spotify:track:abc"]])
def test_to_spotify_uri_rejects_non_text(value):
    assert to_spotify_uri(value) is None


# --- Ported from tests/test_nfc_reader.py (TestIsValidSpotifyUri, TestSpotifyUrlToUri) ---


@pytest.mark.parametrize(
    "uri",
    [
        "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        "spotify:album:6dVIqQ8qmQ5GBnJ9shOYGE",
        "spotify:artist:0OdUWJ0sBjDrqHygGUXeCF",
        "spotify:episode:512ojhOuo1ktJprKbVcKyQ",
        "spotify:show:2MAi0BvDc6GTFvKFPXnkCL",
        "spotify:audiobook:7iHfbu1YPACw6oZPAFJtqe",
        "spotify:chapter:0D5wENdkdwbqlrHoaJ9g29",
    ],
)
def test_ported_valid_native_uris(uri):
    assert to_spotify_uri(uri) == uri


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6", "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"),
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        ),
        ("http://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE", "spotify:album:6dVIqQ8qmQ5GBnJ9shOYGE"),
        ("https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF", "spotify:artist:0OdUWJ0sBjDrqHygGUXeCF"),
        (
            "https://open.spotify.com/audiobook/7iHfbu1YPACw6oZPAFJtqe",
            "spotify:audiobook:7iHfbu1YPACw6oZPAFJtqe",
        ),
        (
            "https://open.spotify.com/chapter/0D5wENdkdwbqlrHoaJ9g29",
            "spotify:chapter:0D5wENdkdwbqlrHoaJ9g29",
        ),
        ("spotify:album:abc123", "spotify:album:abc123"),
    ],
)
def test_ported_url_to_uri(url, expected):
    assert to_spotify_uri(url) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "https://evil.com/spotify.com/track/abc",
        "https://open.spotify.com.evil.com/track/abc",
        "https://example.com/playlist/abc",
        "ftp://open.spotify.com/track/abc",
        "spotify:invalid:abc",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://notspotify.com/track/abc123",
        "https://example.com/foo",
    ],
)
def test_ported_rejects_non_spotify(text):
    assert to_spotify_uri(text) is None


# --- spotify_uri_from_record ---


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (ndef.UriRecord("https://open.spotify.com/track/abc123"), "spotify:track:abc123"),
        (ndef.TextRecord("https://open.spotify.com/playlist/xyz789"), "spotify:playlist:xyz789"),
        (ndef.TextRecord("spotify:album:def456"), "spotify:album:def456"),
        (ndef.UriRecord("https://example.com/something"), None),
        (ndef.TextRecord("WIFI:S:Net;T:WPA;P:pass;;"), None),
        (ndef.wifi.WifiSimpleConfigRecord(), None),
        (SimpleNamespace(uri="", text="spotify:show:abc"), "spotify:show:abc"),
        (SimpleNamespace(uri=None, text=None), None),
        (object(), None),
    ],
)
def test_spotify_uri_from_record(record, expected):
    assert spotify_uri_from_record(record) == expected
