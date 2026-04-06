# Audio-Player-NFC

A standalone NFC-triggered Spotify player built on a **Raspberry Pi Zero 2W** –
think of it as a "Toniebox for adults".  Hold an NFC tag near the reader and
the linked Spotify playlist, album or track starts playing on your Bluetooth
speaker automatically.  No phone, no screen, no technical knowledge required
after the one-time setup.

---

## How it works

```
NFC tag  →  RC522 reader  →  Raspberry Pi Zero 2W  →  Bluetooth speaker
              (SPI/GPIO)        (Spotipy + Raspotify)      (auto-reconnect)
```

1. An NFC tag stores a Spotify URI or an `open.spotify.com` URL in its NDEF
   records (written once from any phone/NFC writer app).
2. The RC522 module reads the tag over SPI.
3. The Python app resolves the URI (direct from NDEF *or* via a UID→URI
   mapping in `config.json`) and calls the Spotify Web API to start playback.
4. [Raspotify](https://github.com/dtcooper/raspotify) (a Spotify Connect
   receiver running on the Pi) streams the audio.
5. PulseAudio routes the audio to the paired Bluetooth speaker.

---

## Hardware requirements

| Component | Example |
|-----------|---------|
| Raspberry Pi Zero 2W | (or any Pi with SPI + Bluetooth) |
| RC522 NFC reader module | Mifare RC522 |
| NFC tags | NTAG213 / NTAG215 / Mifare Classic 1K |
| Bluetooth speaker | Any A2DP-compatible speaker |
| MicroSD card (≥8 GB) | Class 10 / A1 |
| Micro-USB power supply | 5 V / 2.5 A |

### RC522 wiring (SPI0 / CE0)

| RC522 pin | Raspberry Pi GPIO (BCM) |
|-----------|-------------------------|
| SDA       | GPIO 8 (CE0)            |
| SCK       | GPIO 11 (SCLK)          |
| MOSI      | GPIO 10 (MOSI)          |
| MISO      | GPIO 9 (MISO)           |
| GND       | GND                     |
| RST       | GPIO 25                 |
| 3.3 V     | 3.3 V                   |

---

## Quick start

### 1 – Flash Raspberry Pi OS Lite

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash
**Raspberry Pi OS Lite (64-bit)** onto the SD card.  Enable SSH in the
Advanced settings so you can connect headlessly.

### 2 – Edit `config.json` on the boot partition

The SD card's **boot partition is FAT32** – readable on any Windows or Mac
PC without special tools.  Copy `config.example.json` to `/boot/config.json`
(the boot partition root) and fill in your details:

```jsonc
{
  "wifi": [
    { "ssid": "MyHomeNetwork", "password": "MyWifiPassword", "priority": 10 },
    { "ssid": "BackupNetwork",  "password": "BackupPassword",  "priority": 5  }
  ],
  "spotify": {
    "client_id":     "YOUR_SPOTIFY_CLIENT_ID",
    "client_secret": "YOUR_SPOTIFY_CLIENT_SECRET",
    "redirect_uri":  "http://localhost:8888/callback",
    "device_name":   "NFC-Player"
  },
  "bluetooth": {
    "device_name":                "My Bluetooth Speaker",
    "mac_address":                "AA:BB:CC:DD:EE:FF",
    "reconnect_interval_seconds": 10
  },
  "nfc": {
    "reader_type": "rc522",
    "tag_mappings": {
      "AABBCCDD": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    }
  }
}
```

> **Config change workflow** (no SSH needed):  
> Take out the SD card → edit `/boot/config.json` on your laptop → put it
> back → done.

#### Getting Spotify API credentials

1. Go to <https://developer.spotify.com/dashboard> and create an app.
2. Set the Redirect URI to `http://localhost:8888/callback`.
3. Copy the *Client ID* and *Client Secret* into `config.json`.

#### Finding your Bluetooth speaker's MAC address

```bash
bluetoothctl
> scan on
# Wait until your speaker appears; copy its MAC address
> scan off
> exit
```

### 3 – Run the install script (on the Pi)

```bash
git clone https://github.com/Tiro1999/Audio-Player-NFC.git
cd Audio-Player-NFC
sudo bash setup/install.sh
```

The script:
- Installs all system packages (BlueZ, PulseAudio, Python 3, …)
- Enables SPI (needed for RC522)
- Installs [Raspotify](https://github.com/dtcooper/raspotify)
- Creates a Python virtual environment and installs Python packages
- Configures WiFi (`wpa_supplicant.conf`) from `config.json`
- Walks you through Bluetooth pairing
- Completes the Spotify OAuth flow (one-time browser step)
- Installs and enables three systemd services

### 4 – Reboot

```bash
sudo reboot
```

From now on, the Pi will:
- Connect to the first available known WiFi network on boot
- Reconnect to the Bluetooth speaker automatically (and retry if it's off)
- Start Raspotify and wait for NFC tags

---

## Project structure

```
Audio-Player-NFC/
├── config.example.json        # Config template – copy to /boot/config.json
├── requirements.txt
├── src/
│   ├── main.py                # Entry point / main NFC polling loop
│   ├── config_loader.py       # Loads /boot/config.json
│   ├── nfc_reader.py          # RC522 reader + NDEF URI/text parser
│   ├── spotify_controller.py  # Spotipy wrapper for playback control
│   └── bluetooth_manager.py   # bluetoothctl auto-connect + reconnect loop
├── setup/
│   ├── install.sh             # One-time setup script (run as root)
│   ├── nfc-player.service     # systemd service for the main app
│   ├── bt-connect.service     # systemd service for BT auto-reconnect
│   ├── bt-connect.sh          # Shell script for BT connect loop
│   └── wpa_supplicant.conf.example
└── tests/
    ├── test_config_loader.py
    ├── test_nfc_reader.py
    ├── test_spotify_controller.py
    └── test_bluetooth_manager.py
```

---

## Writing NFC tags

Any NFC writer app (e.g. **NFC Tools** for Android/iOS) can write a Spotify
URI or URL to a tag:

| Tag content | Example |
|-------------|---------|
| Spotify URI | `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M` |
| Spotify URL | `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M` |

Alternatively, add the tag's UID to the `nfc.tag_mappings` dictionary in
`config.json` (no NDEF write required – blank tags work).

---

## Systemd services

| Service | Description |
|---------|-------------|
| `raspotify.service` | Spotify Connect receiver (installed by Raspotify) |
| `bt-connect.service` | Keeps the Bluetooth speaker connected (reconnects every 10 s) |
| `nfc-player.service` | Main NFC polling loop; depends on the two services above |

Check logs:

```bash
journalctl -u nfc-player  -f
journalctl -u bt-connect   -f
journalctl -u raspotify    -f
```

---

## Development & testing

```bash
pip install pytest
python -m pytest tests/ -v
```

All tests run without hardware by mocking the RC522 driver and Spotipy client.

---

## WiFi configuration

Multiple networks are supported; the Pi connects to whichever is in range
with the highest `priority` value.  WiFi is configured via
`/etc/wpa_supplicant/wpa_supplicant.conf` (written automatically by the
install script from `config.json`).

To add a new network later: edit `/boot/config.json` and re-run:

```bash
sudo python3 - <<'EOF'
import json, pathlib
cfg = json.load(open("/boot/config.json"))
# … (same logic as in install.sh)
EOF
sudo wpa_cli -i wlan0 reconfigure
```

Or simply re-run `sudo bash setup/install.sh` – it is idempotent.

---

## License

MIT
