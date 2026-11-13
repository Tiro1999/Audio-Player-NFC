# Project Profile

Fill in per project; values in `<angle brackets>` are unset. Every agent reads this file.
The universal rules live in `.claude/rules/` and stay untouched.

| Field | Value |
|---|---|
| Purpose | Standalone NFC player on a Raspberry Pi Zero 2 W: tap a tag → Spotify plays on a Bluetooth speaker; WiFi tags switch the WLAN |
| Type | embedded |
| Language | Python 3.13 (device), Bash (provisioning) |
| SDK / Framework | Raspberry Pi OS Lite 64-bit (Debian 13 Trixie), NetworkManager 1.52 (nmcli), BlueZ 5.82, PipeWire 1.4 / WirePlumber 0.5, go-librespot v0.10.5 (pinned), adafruit-circuitpython-pn532 2.4.9 + adafruit-blinka 10.2.0 (pinned), ndeflib 0.3.3 |
| Target | Raspberry Pi Zero 2 W + PN532 NFC reader (I2C) + Bluetooth A2DP speaker |
| Test hardware | The user's Pi Zero 2 W via SSH (`.env`: `PI_HOST`, `PI_USER`); deploy or provision only when the user asks |
| Default tasks | Build → `Build: Bundle` · Test → `Test: Unit` · Flash/Run → `Pi: Deploy` |
| Environment | Linux/WSL: `. .venv/bin/activate` · Windows: tasks use `.venv\Scripts\python.exe` |
| Version source | `git describe --tags --always --dirty` |
