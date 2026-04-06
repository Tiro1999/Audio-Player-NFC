#!/usr/bin/env python3
"""Spotify OAuth – Wrapper für lokale PC-Ausführung.

Liest config.json aus dem Projektroot, führt den OAuth-Flow aus
und speichert spotify_cache im Projektroot (für flash.sh).

Nutzung:
    cd Audio-Player-NFC
    devTools\\venv\\Scripts\\activate      (Windows)
    python devTools/run_spotify_auth.py
"""

import json
import os
import sys
import webbrowser

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    sys.exit(
        "❌  spotipy nicht installiert.\n"
        "    Führe zuerst aus:  devTools\\setup.bat"
    )

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CACHE_PATH = os.path.join(PROJECT_ROOT, "spotify_cache")


def main():
    print()
    print("========================================")
    print("  🔑  Spotify OAuth – Token generieren")
    print("========================================")
    print()

    # ── Config laden ──────────────────────────────────────────────────
    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            f"❌  {CONFIG_PATH} nicht gefunden.\n"
            "    Kopiere config.json.example → config.json und trage\n"
            "    deine Spotify Client ID + Secret ein."
        )

    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    spotify = cfg.get("spotify", {})
    client_id = spotify.get("client_id", "")
    client_secret = spotify.get("client_secret", "")
    redirect_uri = spotify.get("redirect_uri", "http://127.0.0.1:8888/callback")

    if not client_id or client_id == "your_spotify_client_id":
        sys.exit(
            "❌  spotify.client_id ist nicht gesetzt in config.json.\n"
            "    Erstelle eine App auf https://developer.spotify.com/dashboard"
        )
    if not client_secret or client_secret == "your_spotify_client_secret":
        sys.exit(
            "❌  spotify.client_secret ist nicht gesetzt in config.json.\n"
            "    Findest du unter App → Settings → View client secret"
        )

    print(f"  Config:       {CONFIG_PATH}")
    print(f"  Client ID:    {client_id[:8]}…")
    print(f"  Redirect URI: {redirect_uri}")
    print(f"  Cache:        {CACHE_PATH}")
    print()

    # ── OAuth Flow ────────────────────────────────────────────────────
    print("🌐  Browser öffnet sich gleich für den Spotify Login …")
    print("    Falls nicht, öffne den Link manuell.\n")

    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SCOPES,
            cache_path=CACHE_PATH,
            open_browser=True,
        )
    )

    user = sp.current_user()
    print(f"✅  Eingeloggt als: {user['display_name']} ({user['id']})")
    print(f"📁  Token gespeichert: {CACHE_PATH}")
    print()
    print("Nächster Schritt:")
    print("  ./flash.sh ausführen – spotify_cache wird automatisch auf den Pi übertragen.")
    print()


if __name__ == "__main__":
    main()
