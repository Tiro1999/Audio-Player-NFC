# Spotify Setup Guide

This guide walks you through setting up Spotify for the NFC Spotify Player.
You only need to do this **once** per device.

---

## Prerequisites

- A **Spotify Premium** account (required for Spotify Connect / remote playback)
- A PC with Python 3 installed (for the one-time OAuth token generation)
- Your `config.json` ready (see `config.json.example`)

---

## Step 1: Create a Spotify Developer App

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click **"Create App"**
4. Fill in the form:

   | Field             | Value                                    |
   |-------------------|------------------------------------------|
   | App name          | `NFC Spotify Player` (or any name)       |
   | App description   | `NFC tag triggered Spotify playback`     |
   | Redirect URI      | `http://127.0.0.1:8888/callback`         |

5. Under **"Which API/SDKs are you planning to use?"**, check **Web API**
6. Accept the terms and click **"Save"**

> ⚠️ The Redirect URI must be **exactly** `http://127.0.0.1:8888/callback` — no trailing slash, no https.

---

## Step 2: Copy Your Credentials

1. Open your newly created app in the Dashboard
2. Click **"Settings"** (top right)
3. You will see:
   - **Client ID** — copy this
   - **Client Secret** — click *"View client secret"* and copy it

> 🔒 Keep your Client Secret private! Never share it publicly or commit it to git.

---

## Step 3: Add Credentials to config.json

Open `config.json` and fill in the `spotify` section:

```json
{
  "spotify": {
    "client_id": "paste_your_client_id_here",
    "client_secret": "paste_your_client_secret_here",
    "redirect_uri": "http://127.0.0.1:8888/callback",
    "device_name": "NFC-Box"
  }
}
```

- `device_name` is the name your Pi will appear as in Spotify Connect (default: `NFC-Box`)
- Save the file

---

## Step 4: Generate the OAuth Token

This step runs on your **PC** (not the Pi), because it opens a browser for Spotify login.

### Option A: Using the devTools helper (Recommended for Windows)

```bash
cd devTools
setup_venv.bat
python ..\tools\spotify_auth.py --config ..\config.json
```

### Option B: Direct (any OS)

```bash
pip install spotipy
python3 tools/spotify_auth.py --config config.json
```

### Option C: Without config.json

```bash
python3 tools/spotify_auth.py --client-id YOUR_CLIENT_ID --client-secret YOUR_SECRET
```

### What happens:

1. A browser window opens with the Spotify login page
2. Log in and click **"Agree"** to grant access
3. The browser redirects to `127.0.0.1:8888/callback` — the script catches this automatically
4. You see: `✅ Authenticated as: YourName`
5. A file called `spotify_cache` is created in the project root

> 💡 If the browser doesn't open automatically, copy the URL from the terminal and paste it manually.

---

## Step 5: Deploy the Token to the Pi

The `spotify_cache` file contains your OAuth token. It needs to be on the Pi.

### Option A: Via flash.sh (automatic)

If `spotify_cache` exists in the project root, `flash.sh` copies it automatically:

```bash
bash flash.sh
```

### Option B: Manual SCP

```bash
scp spotify_cache user@<PI_IP>:~/nfc-player/spotify_cache
```

### Option C: Via SD Card

1. Remove the SD card from the Pi
2. Insert it into your PC
3. Copy `spotify_cache` to the boot partition (the one you can see in Explorer/Finder)
4. The Pi will auto-migrate it to the project directory on first boot

---

## Step 6: Verify

SSH into the Pi and test playback:

```bash
nfc-test "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
```

If you see `✅ Playback started!`, everything is working!

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `No devices available` | Make sure Raspotify is running: `systemctl status raspotify` |
| `Token expired` | Re-run `spotify_auth.py` on your PC and redeploy `spotify_cache` |
| `Premium required` | Spotify Connect only works with Spotify Premium accounts |
| Browser doesn't open | Copy the URL from the terminal and paste it in your browser |
| `INVALID_CLIENT` error | Double-check Client ID and Client Secret in config.json |
| `Redirect URI mismatch` | Make sure the redirect URI in the Dashboard matches **exactly**: `http://127.0.0.1:8888/callback` |

---

## Token Refresh

The OAuth token **auto-refreshes** as long as the `spotify_cache` file is present.
You should only need to re-run `spotify_auth.py` if:

- You revoke the app's access in your [Spotify account settings](https://www.spotify.com/account/apps/)
- The `spotify_cache` file gets deleted
- You change the Client ID or Client Secret

---

## Spotify App Quota (Important)

By default, new Spotify apps are in **Development Mode** with a limit of **25 users**.
Since this NFC Player only uses **your own account**, this is perfectly fine —
you do **not** need to request an extension.

If you want other Spotify accounts to use the same app, you need to add them
as users in the Dashboard under **"User Management"**.
