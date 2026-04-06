# LOCATION.md – File Mapping & SCP Commands

This document shows where each file from this repo needs to go on the
Raspberry Pi and provides ready-to-use SCP commands.

## Configuration

Connection details are read from your `.env` file (see `.env.example`):

```env
PI_IP=192.168.0.0
PI_USER=user
```

> **Automated deploy:** Run `bash deploy.sh` to copy all files at once.

## Quick Setup (manual)

```bash
# Source your .env for the variables
source .env

# 1. Copy the entire project to the Pi
scp -r  src/ setup/ requirements.txt  $PI_USER@$PI_IP:~/nfc-player/

# 2. Copy config to the boot partition (FAT32, editable from any PC)
scp  config.json       $PI_USER@$PI_IP:/boot/firmware/config.json

# 3. Copy Spotify token cache to the boot partition
scp  spotify_cache     $PI_USER@$PI_IP:/boot/firmware/spotify_cache
```

## Detailed File Mapping

### Project files → `~/nfc-player/`

| Local Path | Pi Path | Description |
|---|---|---|
| `src/main.py` | `~/nfc-player/src/main.py` | Main entry point |
| `src/config.py` | `~/nfc-player/src/config.py` | Config reader |
| `src/nfc_reader.py` | `~/nfc-player/src/nfc_reader.py` | NFC tag reader |
| `src/spotify_player.py` | `~/nfc-player/src/spotify_player.py` | Spotify API |
| `src/bt_connect.py` | `~/nfc-player/src/bt_connect.py` | BT auto-connect |
| `src/__init__.py` | `~/nfc-player/src/__init__.py` | Package marker |
| `requirements.txt` | `~/nfc-player/requirements.txt` | pip dependencies |
| `setup/install.sh` | `~/nfc-player/setup/install.sh` | Installer script |
| `setup/nfc-player.service` | `~/nfc-player/setup/nfc-player.service` | systemd service |
| `setup/bt-autoconnect.service` | `~/nfc-player/setup/bt-autoconnect.service` | systemd service |

### Config & auth → `/boot/firmware/` (FAT32 boot partition)

| Local Path | Pi Path | Description |
|---|---|---|
| `config.json` | `/boot/firmware/config.json` | Your filled-in config |
| `spotify_cache` | `/boot/firmware/spotify_cache` | OAuth token (from `tools/spotify_auth.py`) |

> **Tip:** You can also put the SD card directly into your PC – the boot
> partition shows up as a drive. Just copy `config.json` and `spotify_cache`
> there.

## SCP Commands (individual files)

```bash
source .env

# --- Project source ---
scp  src/main.py              $PI_USER@$PI_IP:~/nfc-player/src/main.py
scp  src/config.py            $PI_USER@$PI_IP:~/nfc-player/src/config.py
scp  src/nfc_reader.py        $PI_USER@$PI_IP:~/nfc-player/src/nfc_reader.py
scp  src/spotify_player.py    $PI_USER@$PI_IP:~/nfc-player/src/spotify_player.py
scp  src/bt_connect.py        $PI_USER@$PI_IP:~/nfc-player/src/bt_connect.py
scp  src/__init__.py          $PI_USER@$PI_IP:~/nfc-player/src/__init__.py

# --- Setup & services ---
scp  requirements.txt         $PI_USER@$PI_IP:~/nfc-player/requirements.txt
scp  setup/install.sh         $PI_USER@$PI_IP:~/nfc-player/setup/install.sh
scp  setup/nfc-player.service $PI_USER@$PI_IP:~/nfc-player/setup/nfc-player.service
scp  setup/bt-autoconnect.service $PI_USER@$PI_IP:~/nfc-player/setup/bt-autoconnect.service

# --- Config & token (boot partition) ---
scp  config.json              $PI_USER@$PI_IP:/boot/firmware/config.json
scp  spotify_cache            $PI_USER@$PI_IP:/boot/firmware/spotify_cache
```

## After Copying

SSH into the Pi and run:

```bash
cd ~/nfc-player
bash setup/install.sh
sudo reboot
```

## Updating After Changes

If you edit source files locally, push just the changed file:

```bash
source .env
scp  src/main.py  $PI_USER@$PI_IP:~/nfc-player/src/main.py
ssh  $PI_USER@$PI_IP  "sudo systemctl restart nfc-player"
```

If you edit `config.json`:

```bash
source .env
scp  config.json  $PI_USER@$PI_IP:/boot/firmware/config.json
ssh  $PI_USER@$PI_IP  "sudo systemctl restart nfc-player"
```
