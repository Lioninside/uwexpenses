@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtuelle Umgebung nicht gefunden.
    echo Bitte zuerst install.bat ausfuehren.
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe main.py

if errorlevel 1 (
    echo.
    echo Die App wurde mit einem Fehler beendet.
    echo Bitte Fehlermeldung oben pruefen.
    pause
)
