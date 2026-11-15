"""nfc-test: plays a Spotify URI or link on the receiver, as if a tag had been read."""

import argparse
import logging
import sys

from nfc_player.core.build_info import load_build_info
from nfc_player.core.log import setup_logging
from nfc_player.spotify.receiver import Receiver, ReceiverError
from nfc_player.spotify.receiver_config import load_device_name
from nfc_player.spotify.uri import to_spotify_uri

log = logging.getLogger(__name__)

EXAMPLES = (
    "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
    "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
    "https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nfc-test", description="Play a Spotify URI or link on the receiver, as if a tag had been read."
    )
    parser.add_argument("uri", help="spotify:<type>:<id> or an https://open.spotify.com/ link")
    args = parser.parse_args(argv)
    setup_logging(load_build_info().maturity)
    uri = to_spotify_uri(args.uri)
    if uri is None:
        print(f"Not a Spotify URI or link: {args.uri!r}", file=sys.stderr)
        print("Examples:", *EXAMPLES, sep="\n  ", file=sys.stderr)
        return 1
    try:
        Receiver(device_name=load_device_name()).play(uri)
    except ReceiverError as exc:
        log.error("Playback failed: %s", exc)
        return 1
    log.info("Playing %s", uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
