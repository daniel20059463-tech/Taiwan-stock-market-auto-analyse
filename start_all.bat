@echo off
cd /d "E:\claude code test"

REM Start backend service in the background.
start "TaiwanAlphaRadar-Backend" /MIN "E:\claude code test\.venv\Scripts\python.exe" "E:\claude code test\run.py"

REM Give the backend a short head start before opening the desktop app.
timeout /t 3 /nobreak >nul

REM Launch the desktop application.
start "" "E:\claude code test\src-tauri\target\release\taiwan_alpha_radar.exe"
