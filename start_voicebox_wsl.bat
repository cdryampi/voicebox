@echo off
echo ===========================================
echo       VOICEBOX LAUNCHER (WSL MODE)
echo              RTX 5080 ENABLED
echo ===========================================
echo.
echo Stopping any running background processes...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1
echo.
echo Starting Voicebox Backend (WSL)...
echo Ensuring setup_wsl.sh is executable...
wsl -d Ubuntu-24.04 --cd "%~dp0" chmod +x setup_wsl.sh

echo Launching Backend...
start "Voicebox Backend (WSL)" wsl -d Ubuntu-24.04 --cd "%~dp0" bash -c "source backend/.venv_wsl/bin/activate && python3 -m uvicorn backend.main:app --reload --port 17493 --host 0.0.0.0"

echo Starting Voicebox Web Frontend...
start "Voicebox Web" cmd /k "cd web && bun run dev --port 5174"

echo Voicebox started!
echo Backend logs are in the "Voicebox Backend (WSL)" window.
echo Frontend logs are in the "Voicebox Web" window.
