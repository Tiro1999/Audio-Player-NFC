@echo off
REM ================================================================
REM  Setup der devTools-Umgebung (einmalig ausfuehren)
REM  Erstellt ein Python venv und installiert spotipy
REM ================================================================

cd /d "%~dp0"

echo ========================================
echo   devTools - Setup
echo ========================================
echo.

if exist venv (
    echo venv existiert bereits, ueberspringe Erstellung ...
) else (
    echo Erstelle Python venv ...
    python -m venv venv
)

echo Installiere Dependencies ...
call venv\Scripts\activate.bat
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo.
echo ========================================
echo   Setup abgeschlossen!
echo ========================================
echo.
echo   Nutzung:
echo     1. venv aktivieren:  devTools\venv\Scripts\activate
echo     2. Auth ausfuehren:  python devTools\run_spotify_auth.py
echo.
