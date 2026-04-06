#!/usr/bin/env python3
"""Generate the Spotify OAuth token cache (run this on your PC, not the Pi).

Usage:
    1.  pip install spotipy
    2a. python tools/spotify_auth.py --config config.json.example
    2b. python tools/spotify_auth.py --client-id ID --client-secret SECRET

A browser window will open for Spotify login.  After granting access the
token is stored in a file called ``spotify_cache`` in the project root.

Copy that file to the Pi's boot partition:
    scp spotify_cache  <USER>@<PI_IP>:/boot/firmware/spotify_cache
"""

import argparse
import json
import os
import sys

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    sys.exit("spotipy is not installed.  Run:  pip install spotipy")

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"


def main():
    parser = argparse.ArgumentParser(description="Generate Spotify OAuth token")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--client-id", help="Spotify Client ID")
    parser.add_argument("--client-secret", help="Spotify Client Secret")
    args = parser.parse_args()

    if args.config:
        with open(args.config) as f:
            cfg = json.load(f)
        client_id = cfg["spotify"]["client_id"]
        client_secret = cfg["spotify"]["client_secret"]
        redirect_uri = cfg["spotify"].get("redirect_uri", "http://127.0.0.1:8888/callback")
    elif args.client_id and args.client_secret:
        client_id = args.client_id
        client_secret = args.client_secret
        redirect_uri = "http://127.0.0.1:8888/callback"
    else:
        parser.error("Provide --config OR both --client-id and --client-secret")

    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "spotify_cache")
    cache_path = os.path.normpath(cache_path)

    print(f"\n🔑 Starting Spotify OAuth flow …")
    print(f"   Client ID : {client_id[:8]}…")
    print(f"   Redirect  : {redirect_uri}")
    print(f"   Cache file: {cache_path}\n")

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SCOPES,
            cache_path=cache_path,
            open_browser=True,
        )
    )

    user = sp.current_user()
    print(f"✅ Authenticated as: {user['display_name']} ({user['id']})")
    print(f"\n📁 Token saved to: {cache_path}")
    print()
    print("Next steps:")
    print(f"  1. Copy to Pi:  scp {cache_path}  <USER>@<PI_IP>:/boot/firmware/spotify_cache")
    print("  2. Or insert the SD card into your PC and copy spotify_cache to the boot partition")


if __name__ == "__main__":
    main()
