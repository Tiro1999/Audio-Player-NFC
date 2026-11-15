"""Spotify URIs: tag text and config values become spotify:<type>:<id>; anything else is rejected."""

import re
from typing import Any
from urllib.parse import urlsplit

SPOTIFY_TYPES = ("track", "album", "playlist", "artist", "episode", "show", "audiobook", "chapter")

_TYPE = "|".join(SPOTIFY_TYPES)
_ID = "[A-Za-z0-9]{1,64}"
_NATIVE = re.compile(f"spotify:(?:{_TYPE}):{_ID}")
# Optional locale segment (/intl-de/, /intl-pt-br/), then /<type>/<id>.
_WEB_PATH = re.compile(f"/(?:intl-[A-Za-z]{{2}}(?:-[A-Za-z]{{2}})?/)?({_TYPE})/({_ID})")
# The whole netloc must match: this also rules out userinfo ("user@host") and other ports.
_WEB_NETLOCS = ("open.spotify.com", "open.spotify.com:", "open.spotify.com:80", "open.spotify.com:443")


def to_spotify_uri(text: str) -> str | None:
    """spotify:<type>:<id> from a native URI or an open.spotify.com link; None for anything else.

    Surrounding whitespace is ignored, as are the query and fragment of a link.
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    if _NATIVE.fullmatch(text):
        return text
    if not text.isprintable():
        return None  # urlsplit would silently drop tabs and newlines
    try:
        parts = urlsplit(text)
    except ValueError:  # e.g. a bracketed host that is no IP address
        return None
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in _WEB_NETLOCS:
        return None
    match = _WEB_PATH.fullmatch(parts.path)
    return f"spotify:{match[1]}:{match[2]}" if match else None


def spotify_uri_from_record(record: Any) -> str | None:
    """The Spotify URI of an NDEF URI or Text record (ndeflib); None for any other record."""
    return to_spotify_uri(getattr(record, "uri", None) or getattr(record, "text", None))
