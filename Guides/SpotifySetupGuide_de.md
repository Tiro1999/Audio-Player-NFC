# Spotify Einrichtungsanleitung

Diese Anleitung führt dich Schritt für Schritt durch die Einrichtung von Spotify
für den NFC Spotify Player. Das muss nur **einmal** pro Gerät gemacht werden.

---

## Voraussetzungen

- Ein **Spotify Premium** Account (nötig für Spotify Connect / Fernsteuerung der Wiedergabe)
- Ein PC mit Python 3 (für die einmalige OAuth-Token-Generierung)
- Deine `config.json` vorbereitet (siehe `config.json.example`)

---

## Schritt 1: Spotify Developer App erstellen

1. Öffne das [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Melde dich mit deinem Spotify-Konto an
3. Klicke auf **„Create App"**
4. Fülle das Formular aus:

   | Feld              | Wert                                     |
   |-------------------|------------------------------------------|
   | App name          | `NFC Spotify Player` (oder ein beliebiger Name) |
   | App description   | `NFC tag triggered Spotify playback`     |
   | Redirect URI      | `http://127.0.0.1:8888/callback`         |

5. Unter **„Which API/SDKs are you planning to use?"** hake **Web API** an
6. Akzeptiere die Nutzungsbedingungen und klicke auf **„Save"**

> ⚠️ Die Redirect URI muss **exakt** `http://127.0.0.1:8888/callback` lauten — kein abschließender Schrägstrich, kein https.

---

## Schritt 2: Zugangsdaten kopieren

1. Öffne deine neu erstellte App im Dashboard
2. Klicke auf **„Settings"** (oben rechts)
3. Du siehst:
   - **Client ID** — kopiere diese
   - **Client Secret** — klicke auf *„View client secret"* und kopiere es

> 🔒 Halte dein Client Secret geheim! Teile es niemals öffentlich und committe es nicht in Git.

---

## Schritt 3: Zugangsdaten in config.json eintragen

Öffne `config.json` und fülle den `spotify`-Abschnitt aus:

```json
{
  "spotify": {
    "client_id": "deine_client_id_hier_einfuegen",
    "client_secret": "dein_client_secret_hier_einfuegen",
    "redirect_uri": "http://127.0.0.1:8888/callback",
    "device_name": "NFC-Box"
  }
}
```

- `device_name` ist der Name, unter dem dein Pi in Spotify Connect erscheint (Standard: `NFC-Box`)
- Datei speichern

---

## Schritt 4: OAuth-Token generieren

Dieser Schritt wird auf deinem **PC** ausgeführt (nicht auf dem Pi), weil ein Browser für den Spotify-Login benötigt wird.

### Option A: Mit dem devTools-Helper (Empfohlen für Windows)

```bash
cd devTools
setup_venv.bat
python ..\tools\spotify_auth.py --config ..\config.json
```

### Option B: Direkt (jedes Betriebssystem)

```bash
pip install spotipy
python3 tools/spotify_auth.py --config config.json
```

### Option C: Ohne config.json

```bash
python3 tools/spotify_auth.py --client-id DEINE_CLIENT_ID --client-secret DEIN_SECRET
```

### Was passiert:

1. Ein Browserfenster öffnet sich mit der Spotify-Loginseite
2. Melde dich an und klicke auf **„Zustimmen"**
3. Der Browser leitet auf `127.0.0.1:8888/callback` um — das Skript fängt das automatisch ab
4. Du siehst: `✅ Authenticated as: DeinName`
5. Eine Datei namens `spotify_cache` wird im Projektordner erstellt

> 💡 Wenn sich der Browser nicht automatisch öffnet, kopiere die URL aus dem Terminal und füge sie manuell ein.

---

## Schritt 5: Token auf den Pi übertragen

Die Datei `spotify_cache` enthält dein OAuth-Token und muss auf dem Pi vorhanden sein.

### Option A: Über flash.sh (automatisch)

Wenn `spotify_cache` im Projektordner existiert, kopiert `flash.sh` die Datei automatisch mit:

```bash
bash flash.sh
```

### Option B: Manuell per SCP

```bash
scp spotify_cache user@<PI_IP>:~/nfc-player/spotify_cache
```

### Option C: Über die SD-Karte

1. SD-Karte aus dem Pi entfernen
2. In den PC einstecken
3. `spotify_cache` auf die Boot-Partition kopieren (die Partition, die im Explorer/Finder sichtbar ist)
4. Der Pi migriert die Datei beim nächsten Start automatisch ins Projektverzeichnis

---

## Schritt 6: Überprüfen

Per SSH auf den Pi verbinden und Wiedergabe testen:

```bash
nfc-test "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
```

Wenn du `✅ Playback started!` siehst, funktioniert alles!

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| `No devices available` | Prüfe ob Raspotify läuft: `systemctl status raspotify` |
| `Token expired` | Führe `spotify_auth.py` erneut auf dem PC aus und übertrage `spotify_cache` |
| `Premium required` | Spotify Connect funktioniert nur mit Spotify Premium |
| Browser öffnet sich nicht | Kopiere die URL aus dem Terminal und füge sie im Browser ein |
| `INVALID_CLIENT` Fehler | Überprüfe Client ID und Client Secret in config.json |
| `Redirect URI mismatch` | Stelle sicher, dass die Redirect URI im Dashboard **exakt** übereinstimmt: `http://127.0.0.1:8888/callback` |

---

## Token-Aktualisierung

Das OAuth-Token **erneuert sich automatisch**, solange die Datei `spotify_cache` vorhanden ist.
Du musst `spotify_auth.py` nur erneut ausführen, wenn:

- Du den App-Zugriff in deinen [Spotify-Kontoeinstellungen](https://www.spotify.com/account/apps/) widerrufst
- Die `spotify_cache`-Datei gelöscht wird
- Du die Client ID oder das Client Secret änderst

---

## Spotify App-Kontingent (Wichtig)

Standardmäßig befinden sich neue Spotify-Apps im **Development Mode** mit einem Limit von **25 Nutzern**.
Da der NFC Player nur **dein eigenes Konto** verwendet, ist das völlig ausreichend —
du musst **keine** Erweiterung beantragen.

Wenn du möchtest, dass andere Spotify-Konten dieselbe App nutzen, musst du sie
im Dashboard unter **„User Management"** als Nutzer hinzufügen.
