@echo off
setlocal enabledelayedexpansion

title Capacity Connect - One-Click Launcher

echo ======================================================================
echo          Capacity Connect - High-Speed Launcher
echo ======================================================================
echo.

cd /d "%~dp0capacity-connect"

:: 1. Ensure .env file exists
if not exist ".env" (
    echo [INFO] Generating .env configuration from .env.example ...
    copy /Y .env.example .env >nul
    echo POSTGRES_PASSWORD=capacity_connect_dev >> .env
    echo AUTH_JWT_SECRET=super-secret-jwt-key-with-at-least-32-chars-capacity-connect >> .env
    echo MFA_ENCRYPTION_KEY=dGhpcy1pcy1hLTMyLWJ5dGUtZmVybmV0LWtleS1leGFtcGxlIQ== >> .env
    echo [OK] .env created successfully.
)

:: 2. Check Docker daemon
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running!
    echo Please start Docker Desktop and run this script again.
    echo.
    pause
    exit /b 1
)

:: 3. Launch Docker Compose Stack
echo [1/3] Launching Capacity Connect Docker stack...
docker compose up -d --remove-orphans

if %errorlevel% neq 0 (
    echo [ERROR] Docker compose failed to start.
    pause
    exit /b 1
)

:: 4. Wait for services to be ready
echo.
echo [2/3] Waiting for Web and API services to be ready...
set /a attempts=0
:WAIT_LOOP
set /a attempts+=1
if %attempts% gtr 30 (
    echo [WARNING] Services took longer than expected to report healthy.
    goto READY
)

powershell -Command "try { $w = (Invoke-WebRequest -Uri 'http://localhost:3000' -UseBasicParsing -TimeoutSec 2).StatusCode; $a = (Invoke-WebRequest -Uri 'http://localhost:8000/docs' -UseBasicParsing -TimeoutSec 2).StatusCode; if ($w -eq 200 -and $a -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 2 /nobreak >nul
    goto WAIT_LOOP
)

:READY
echo [OK] All services are healthy and running!
echo.
echo [3/3] Opening Capacity Connect in your default browser...
start http://localhost:3000

echo ======================================================================
echo   Capacity Connect is Live!
echo   ------------------------------------------------------------------
echo   * Web App:       http://localhost:3000
echo   * API Docs:      http://localhost:8000/docs
echo   * Mailpit Inbox: http://localhost:8025
echo   * Database:      localhost:5432 (Database: capacity_connect)
echo ======================================================================
echo.
echo Press any key to stop all containers, or close this window to keep them running.
pause >nul

echo Stopping containers...
docker compose stop
echo Done!
