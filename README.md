# Audio-Player-NFC

A standalone NFC-based Spotify player for the **Raspberry Pi Zero 2 W**.
Scan an NFC tag → music plays on your Bluetooth speaker. No screen, no app – just tap & play.

## How It Works

```
NFC Tag  →  PN532 (I2C)  →  Python app
                                 ↓
                          Spotify Web API
                          "Play this URI"
                                 ↓
                          Raspotify (librespot)
                          receives audio stream
                                 ↓
                          PulseAudio → Bluetooth A2DP → Speaker
```

## Hardware

| Component | Model |
|-----------|-------|
| Board | Raspberry Pi Zero 2 W |
| OS | Raspberry Pi OS Lite (Bookworm) |
| NFC Reader | PN532 NFC/RFID Module V3 |
| Speaker | Any Bluetooth A2DP speaker |

### Wiring (PN532 → Pi via I2C)

| PN532 Pin | Pi Pin | Description |
|-----------|--------|-------------|
| VCC | Pin 1 (3.3 V) | Power |
| GND | Pin 6 (GND) | Ground |
| SDA | Pin 3 (GPIO 2) | I2C Data |
| SCL | Pin 5 (GPIO 3) | I2C Clock |

> Set the PN532 DIP switches to **I2C mode**: SEL0 = ON, SEL1 = OFF.

## Prerequisites

- **Spotify Premium** account (required for playback control via API)
- A [Spotify Developer App](https://developer.spotify.com/dashboard) → note Client ID & Secret
- Set the Redirect URI in your app to `http://localhost:8888/callback`

## Project Structure

```
Audio-Player-NFC/
├── config.json.example          # Template – copy to /boot/firmware/config.json
├── requirements.txt             # Python dependencies
├── src/
│   ├── main.py                  # Main loop: tag → Spotify
│   ├── config.py                # Reads /boot/firmware/config.json
│   ├── nfc_reader.py            # PN532 NFC reader (I2C)
│   ├── spotify_player.py        # Spotify Web API wrapper
│   └── bt_connect.py            # Bluetooth auto-reconnect service
├── setup/
│   ├── install.sh               # One-shot installer (run on Pi)
│   ├── nfc-player.service       # systemd service
│   └── bt-autoconnect.service   # systemd service
├── tools/
│   └── spotify_auth.py          # OAuth token generator (run on PC)
├── tests/
│   └── test_config.py           # Config module tests
├── LOCATION.md                  # SCP file mapping
└── README.md
```

## Setup Guide

### Step 1 – Prepare `config.json`

Copy `config.json.example`, fill in your values, and save as `config.json`:

```json
{
  "wifi": [
    { "ssid": "YourWiFi", "psk": "your-password", "priority": 10 }
  ],
  "bluetooth": {
    "speaker_mac": "AA:BB:CC:DD:EE:FF",
    "speaker_name": "My Speaker"
  },
  "spotify": {
    "client_id": "your_client_id",
    "client_secret": "your_client_secret",
    "redirect_uri": "http://localhost:8888/callback",
    "device_name": "NFC-Box"
  },
  "nfc_tags": {
    "04A1B2C3D4E5F6": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
  },
  "behavior": {
    "pause_on_remove": false
  }
}
```

### Step 2 – Generate Spotify Token (on your PC)

```bash
pip install spotipy
python tools/spotify_auth.py --config config.json
```

A browser opens for Spotify login. After granting access, a `spotify_cache` file is created.

### Step 3 – Copy Files to the Pi

Create your `.env` file from the example and fill in your Pi's IP and username:

```bash
cp .env.example .env
# Edit .env with your values
```

Then deploy with one command:

```bash
bash deploy.sh
```

See **[LOCATION.md](LOCATION.md)** for manual SCP commands and the detailed file mapping.

### Step 4 – Pair Bluetooth Speaker (on the Pi via SSH)

```bash
bluetoothctl
# In bluetoothctl shell:
power on
agent on
scan on
# Wait for your speaker to appear, then:
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
exit
```

### Step 5 – Install & Start (on the Pi via SSH)

```bash
cd ~/nfc-player
bash setup/install.sh
sudo reboot
```

After reboot the Pi will:
1. Connect to WiFi (from your configured list)
2. Auto-connect to the Bluetooth speaker
3. Start Raspotify (Spotify Connect receiver)
4. Wait for NFC tags

### Step 6 – Write NFC Tags

Use any NFC writer app on your phone (e.g. *NFC Tools*):

- **Option A** – Write a Spotify URI as an NDEF record:
  `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`

- **Option B** – Just use the tag's UID and map it in `config.json` under `nfc_tags`.
  To find a tag's UID, hold it to the reader and check the logs:
  ```bash
  journalctl -u nfc-player -f
  ```

## Managing the Device

```bash
# View live logs
journalctl -u nfc-player -f
journalctl -u bt-autoconnect -f

# Restart services
sudo systemctl restart nfc-player
sudo systemctl restart bt-autoconnect

# Edit config (then restart nfc-player)
sudo nano /boot/firmware/config.json
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| NFC reader not found | Check wiring, run `sudo i2cdetect -y 1` (should show `0x24`) |
| Spotify device not found | Check Raspotify: `sudo systemctl status raspotify` |
| No Bluetooth audio | Check connection: `bluetoothctl info AA:BB:CC:DD:EE:FF` |
| Token expired | Re-run `tools/spotify_auth.py` and copy new `spotify_cache` |

## Running Tests

```bash
python -m pytest tests/ -v
```
