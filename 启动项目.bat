@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Project one-click start
echo ============================================
echo.

echo [1/4] Checking Docker infra...
docker info >nul 2>&1
if errorlevel 1 (
    echo     Docker Desktop is NOT running.
    echo     Please open Docker Desktop first, then double-click this file again.
    echo.
    pause
    exit /b 1
)
docker compose -f "backend\docker-compose.infra.yml" up -d
echo     infra ready
echo.

if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [2/4] Starting backend on http://localhost:5001
start "backend 5001" cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-service.ps1" backend

echo [3/4] Starting mock server on http://127.0.0.1:8080
start "mock 8080" cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-service.ps1" mock

echo [4/4] Starting frontend on http://localhost:3000
start "frontend 3000" cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-service.ps1" frontend

echo.
echo All services launched. Open http://localhost:3000 after about 30 seconds.
echo Logs: logs\backend.log  logs\mock.log  logs\frontend.log
echo Close each window to stop the corresponding service.
timeout /t 8 >nul
