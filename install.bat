@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  UwExpenses – Einrichtung / Setup
echo ============================================================
echo.

:: ── Check Python ────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python wurde nicht gefunden.
    echo.
    echo Bitte Python 3.10 oder neuer installieren:
    echo   https://www.python.org/downloads/
    echo.
    echo Wichtig: "Add Python to PATH" beim Installieren anwaehlen.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Python %PYVER% gefunden.
echo.

:: ── Create virtual environment ──────────────────────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo Virtuelle Umgebung wird erstellt ...
    python -m venv .venv
    if errorlevel 1 (
        echo FEHLER: Virtuelle Umgebung konnte nicht erstellt werden.
        pause
        exit /b 1
    )
    echo Virtuelle Umgebung erstellt.
) else (
    echo Virtuelle Umgebung bereits vorhanden.
)
echo.

:: ── Install / upgrade packages ──────────────────────────────────────────────
echo Bibliotheken werden installiert / aktualisiert ...
echo (Dies kann beim ersten Mal einige Minuten dauern.)
echo.

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo FEHLER: Installation fehlgeschlagen. Bitte Fehlermeldung oben pruefen.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Installation erfolgreich abgeschlossen!
echo.
echo  App starten:  start.bat
echo ============================================================
echo.
pause
endlocal
