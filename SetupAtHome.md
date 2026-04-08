# 🏠 Einrichtung & Nutzung – NFC Spotify Player

> **Zielgruppe:** Dieses Dokument erklärt Schritt für Schritt, wie du den NFC Player
> an einem neuen Ort einrichtest – WiFi, Bluetooth Box und NFC Tags.

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#1-voraussetzungen)
2. [WiFi einrichten](#2-wifi-einrichten)
   - [Am Pi per SSH](#21-wifi-am-pi-per-ssh)
   - [Ohne SSH (SD-Karte am PC)](#22-wifi-ohne-ssh-sd-karte-am-pc)
   - [Handy-Hotspot für unterwegs](#23-handy-hotspot-für-unterwegs)
   - [WiFi per NFC Tag (Bonus!)](#24-wifi-per-nfc-tag)
3. [Bluetooth Speaker einrichten](#3-bluetooth-speaker-einrichten)
   - [Neuen Speaker koppeln](#31-neuen-speaker-koppeln)
   - [Bestehende Speaker anzeigen](#32-bestehende-speaker-anzeigen)
   - [Speaker entfernen](#33-speaker-entfernen)
   - [Wie Auto-Reconnect funktioniert](#34-wie-auto-reconnect-funktioniert)
   - [Mehrere Speaker (Prioritäten)](#35-mehrere-speaker-prioritäten)
4. [NFC Tags beschreiben](#4-nfc-tags-beschreiben)
5. [Troubleshooting](#5-troubleshooting)

---

## 1. Voraussetzungen

- **Pi ist eingeschaltet** und mit Strom versorgt (USB-C / Powerbank)
- **SSH-Zugang** zum Pi (über gleiches WiFi oder direkt per Kabel)
- Standard-Login: `ssh user@NFC-SpotiPi.local` (oder IP-Adresse)

> **Tipp:** Wenn du noch gar kein WiFi hast, nutze [Methode 2.2](#22-wifi-ohne-ssh-sd-karte-am-pc)
> (SD-Karte am PC bearbeiten) – dafür brauchst du kein SSH.

---

## 2. WiFi einrichten

### 2.1 WiFi am Pi per SSH

Am schnellsten: per SSH verbinden und das WiFi-Tool nutzen.

```bash
# Verfügbare Netzwerke scannen
nfc-wifi scan

# WiFi hinzufügen (Passwort wird gehasht gespeichert, NIE im Klartext!)
python3 ~/nfc-player/tools/wifi_tools.py add "FreundesWiFi" "DasPasswort123" --priority 5

# Netzwerke in NetworkManager übernehmen
python3 ~/nfc-player/tools/wifi_tools.py apply

# Alle konfigurierten Netzwerke anzeigen
python3 ~/nfc-player/tools/wifi_tools.py list
```

**Prioritäten (1–10):**
| Priorität | Beispiel |
|-----------|----------|
| `10` | Dein Heim-WiFi (bevorzugt) |
| `7` | Eltern / häufige Orte |
| `5` | Standard |
| `3` | Handy-Hotspot (Fallback) |

> Der Pi verbindet sich automatisch mit dem verfügbaren Netzwerk mit der **höchsten Priorität**.

### 2.2 WiFi ohne SSH (SD-Karte am PC)

Wenn du keinen SSH-Zugang hast (z.B. neuer Standort, kein bekanntes WiFi):

1. **Pi ausschalten** (Strom abziehen)
2. **SD-Karte** in den PC/Laptop stecken
3. Die Partition `bootfs` öffnen (wird als Laufwerk angezeigt)
4. Datei **`config.json`** mit einem Texteditor öffnen
5. Neues WiFi im `"wifi"` Array hinzufügen:

```json
{
  "wifi": [
    { "ssid": "MeinHeimWiFi", "psk": "MeinPasswort", "priority": 10 },
    { "ssid": "FreundesWiFi", "psk": "IhrPasswort", "priority": 5 },
    { "ssid": "MeinHandyHotspot", "psk": "HotspotPW", "priority": 3 }
  ]
}
```

6. Speichern, SD-Karte **sicher auswerfen**, zurück in den Pi
7. Pi einschalten → verbindet sich automatisch

> **Hinweis:** Bei dieser Methode steht das Passwort im Klartext in der Datei.
> Beim nächsten `wifi_tools.py apply` wird es automatisch gehasht.

### 2.3 Handy-Hotspot für unterwegs

Perfekt für unterwegs, wenn kein festes WiFi verfügbar ist:

1. **Einmalig einrichten** (per SSH oder SD-Karte):
   ```bash
   python3 ~/nfc-player/tools/wifi_tools.py add "MeinHandy" "HotspotPasswort" --priority 3
   python3 ~/nfc-player/tools/wifi_tools.py apply
   ```

2. **Unterwegs nutzen:**
   - Hotspot auf dem Handy aktivieren (SSID + Passwort müssen identisch sein!)
   - Pi einschalten → findet den Hotspot automatisch → Musik läuft 🎵

> **Tipp:** Niedrige Priorität (`3`), damit der Pi zuhause bevorzugt das Heim-WiFi nutzt.

> **⚠️ Wichtig:** Der Spotify-Player braucht Internet! Ohne WiFi/Hotspot kann der Pi
> keine Musik von Spotify laden.

### 2.4 WiFi per NFC Tag (Bonus!)

> **Status: Idee / Zukunfts-Feature** – aktuell noch nicht automatisch implementiert.
> Du kannst aber jetzt schon einen NFC Tag mit WiFi-Daten beschreiben und manuell nutzen.

Die elegante Variante: Einen NFC Tag mit WiFi-Daten beschreiben, den du bei Freunden
einfach an den Player hältst.

**So würde es funktionieren:**
1. Auf dem Handy mit einer NFC-Writer-App (z.B. *NFC Tools*) einen Tag beschreiben:
   - Typ: **WiFi** (oder Text mit `WIFI:S:FreundesWiFi;T:WPA;P:DasPasswort;;`)
2. Tag an den NFC Reader halten
3. Der Player erkennt den WiFi-Tag und verbindet sich automatisch

**Manueller Workaround für jetzt:**
Einen NFC Tag mit dem WiFi-Info-Text beschreiben und dann per SSH:
```bash
python3 ~/nfc-player/tools/wifi_tools.py add "FreundesSSID" "Passwort" --priority 7
python3 ~/nfc-player/tools/wifi_tools.py apply
```

---

## 3. Bluetooth Speaker einrichten

### 3.1 Neuen Speaker koppeln

**Schritt 1: Speaker in den Pairing-Modus bringen**

Jeder Speaker hat einen Pairing-Modus (meistens Bluetooth-Taste lange drücken,
LED blinkt schnell). Schau ins Handbuch deines Speakers.

| Speaker | Pairing-Modus |
|---------|---------------|
| JBL Charge/Flip | Bluetooth-Taste gedrückt halten bis LED blinkt |
| Bose | Bluetooth-Taste 3 Sek. halten |
| Marshall | Bluetooth-Taste lange drücken |
| UE Boom | Bluetooth-Taste + Power gleichzeitig |

**Schritt 2: Am Pi scannen und verbinden**

```bash
# 1. Nach Bluetooth-Geräten suchen (Speaker muss im Pairing-Modus sein!)
nfc-bt scan

# Ausgabe z.B.:
#   Found 2 device(s):
#     #    MAC Address          Name
#     ──── ──────────────────── ──────────────────────────────
#     1    00:42:79:DF:6C:53    JBL Charge 4
#     2    A0:B1:C2:D3:E4:F5    Bose Mini

# 2. Speaker verbinden (MAC-Adresse von oben kopieren)
nfc-bt connect 00:42:79:DF:6C:53 --priority 10

# Ausgabe:
#   🔗  Connecting to JBL Charge 4 (00:42:79:DF:6C:53) …
#       Scanning for device …
#       Pairing …
#       Connecting …
#   ✅  Connected to JBL Charge 4!
#       Status: paired=True, trusted=True, connected=True
#   ➕  Added new speaker → priority 10
#   💾  Saved to /boot/firmware/config.json
```

**Schritt 3: Testen**

```bash
# Audio-Test (ein kurzer Ton sollte aus dem Speaker kommen)
paplay /usr/share/sounds/alsa/Front_Left.wav

# Spotify-Test (ganzer Song)
nfc-test "https://open.spotify.com/track/5hSnGMuMeAjgIBD1I4G6dq"
```

### 3.2 Bestehende Speaker anzeigen

```bash
# Alle konfigurierten Speaker in config.json anzeigen
nfc-bt list

# Ausgabe:
#   Configured speakers (/boot/firmware/config.json):
#
#     Prio   MAC Address          Name
#     ────── ──────────────────── ──────────────────────────────
#     10     00:42:79:DF:6C:53    JBL Charge 4
#     5      A0:B1:C2:D3:E4:F5    Bose Mini

# Aktuellen Bluetooth-Status vom System anzeigen
bluetoothctl info 00:42:79:DF:6C:53
```

### 3.3 Speaker entfernen

```bash
# Aus config.json entfernen
nfc-bt remove 00:42:79:DF:6C:53

# Optional: Auch aus dem Bluetooth-System entfernen (un-pair)
bluetoothctl remove 00:42:79:DF:6C:53

# Services neu starten, damit der nächste Speaker übernimmt
nfc-restart
```

### 3.4 Wie Auto-Reconnect funktioniert

Der **bt-autoconnect** Service läuft dauerhaft im Hintergrund und macht Folgendes:

```
Boot / Service-Start
      │
      ▼
Alle Speaker aus config.json laden
      │
      ▼
Speaker nach Priorität durchgehen (höchste zuerst)
      │
      ▼
"trust" setzen für alle Speaker → Bluetooth merkt sich das Gerät
      │
      ▼
Verbindung zum ersten erreichbaren Speaker aufbauen
      │
      ▼
PulseAudio Audio-Ausgang auf den BT Speaker umleiten
      │
      ▼
Alle 60 Sek.: Verbindung prüfen, bei Abbruch neu verbinden
```

**Das bedeutet in der Praxis:**
- ✅ **Pi einschalten** → verbindet sich automatisch mit dem Speaker
- ✅ **Speaker aus/einschalten** → Pi verbindet sich automatisch wieder
- ✅ **Anderer Ort, anderer Speaker** → solange er in config.json steht, verbindet er sich
- ✅ **Mehrere Speaker konfiguriert** → der mit der höchsten Priorität & Reichweite wird genommen

### 3.5 Mehrere Speaker (Prioritäten)

Du kannst beliebig viele Speaker konfigurieren. Der Pi verbindet sich mit dem **erreichbaren
Speaker mit der höchsten Priorität**.

**Beispiel-Setup:**

| Priorität | Speaker | Ort |
|-----------|---------|-----|
| `10` | JBL Charge 4 | Zuhause (Haupt-Speaker) |
| `8` | Bose Mini | Bei den Eltern |
| `5` | Marshall Emberton | Unterwegs |

```bash
# Speaker mit verschiedenen Prioritäten hinzufügen
nfc-bt connect 00:42:79:DF:6C:53 --priority 10   # JBL → höchste Prio
nfc-bt connect A0:B1:C2:D3:E4:F5 --priority 8     # Bose → mittlere Prio
nfc-bt connect C1:D2:E3:F4:05:16 --priority 5     # Marshall → niedrigste Prio
```

**Priorität nachträglich ändern:**

```bash
# Gleichen connect-Befehl mit neuer Priorität ausführen → überschreibt den Eintrag
nfc-bt connect 00:42:79:DF:6C:53 --priority 7
```

---

## 4. NFC Tags beschreiben

Jeder NFC Tag braucht einen **Spotify-Link** als NDEF URI Record.

### Mit dem Handy (empfohlen)

1. App installieren: **NFC Tools** (iOS / Android, kostenlos)
2. „Schreiben" → „Datensatz hinzufügen" → **URL/URI**
3. Spotify-Link einfügen, z.B.:
   - Song: `https://open.spotify.com/track/5hSnGMuMeAjgIBD1I4G6dq`
   - Playlist: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
   - Album: `https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv`
4. Tag auf das Handy legen → „Schreiben"

### Spotify-Link finden

1. Spotify App öffnen (Handy oder Desktop)
2. Song / Playlist / Album suchen
3. **Teilen** → **Link kopieren**
4. Diesen Link auf den NFC Tag schreiben

### Testen ohne NFC Tag

```bash
# Direkt einen Spotify-Link injizieren (gleicher Effekt wie Tag scannen)
nfc-test "https://open.spotify.com/track/5hSnGMuMeAjgIBD1I4G6dq"
```

---

## 5. Troubleshooting

### WiFi verbindet sich nicht

```bash
# Status prüfen
nmcli general status
nmcli connection show

# Verfügbare Netzwerke scannen
nmcli dev wifi list

# Manuell verbinden (zum Testen)
sudo nmcli dev wifi connect "SSID" password "Passwort"
```

### Bluetooth Speaker verbindet sich nicht

```bash
# Ist Bluetooth an?
bluetoothctl show | grep Powered

# Speaker-Info anzeigen
bluetoothctl info 00:42:79:DF:6C:53

# Manuell verbinden
bluetoothctl connect 00:42:79:DF:6C:53

# Komplett neu koppeln (erst entfernen, dann neu verbinden)
bluetoothctl remove 00:42:79:DF:6C:53
nfc-bt connect 00:42:79:DF:6C:53 --priority 10

# Service-Log prüfen
journalctl -u bt-autoconnect --no-pager -n 20
```

### Kein Sound

```bash
# PulseAudio-Status prüfen
pactl info
pactl list sinks short

# Test-Ton abspielen
paplay /usr/share/sounds/alsa/Front_Left.wav

# Raspotify-Log prüfen (Audio Sink Errors?)
journalctl -u raspotify --no-pager -n 20

# Alles neu starten
nfc-restart
```

### NFC Tag wird nicht erkannt

```bash
# NFC Player Log ansehen
nfc-log

# Service-Status
nfc-status

# I2C-Verbindung zum PN532 prüfen
i2cdetect -y 1
# → Adresse 0x24 sollte sichtbar sein
```

### Nützliche Befehle (Übersicht)

| Befehl | Beschreibung |
|--------|-------------|
| `nfc-log` | Live Log-Ausgabe |
| `nfc-status` | Status aller Services |
| `nfc-restart` | Alle Services neu starten |
| `nfc-test <URL>` | Spotify-Link testen (ohne NFC Tag) |
| `nfc-bt scan` | BT-Geräte suchen |
| `nfc-bt connect <MAC>` | Speaker koppeln |
| `nfc-bt list` | Konfigurierte Speaker anzeigen |
| `nfc-bt remove <MAC>` | Speaker entfernen |
