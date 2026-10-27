# Capacity Connect - One-Click PowerShell Launcher
$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "          Capacity Connect - High-Speed Launcher" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path "$ScriptDir\capacity-connect"

# 1. Check/create .env
if (-not (Test-Path ".env")) {
    Write-Host "[INFO] Generating .env configuration from .env.example ..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Add-Content -Path ".env" -Value "`nPOSTGRES_PASSWORD=capacity_connect_dev"
    Add-Content -Path ".env" -Value "AUTH_JWT_SECRET=super-secret-jwt-key-with-at-least-32-chars-capacity-connect"
    Add-Content -Path ".env" -Value "MFA_ENCRYPTION_KEY=dGhpcy1pcy1hLTMyLWJ5dGUtZmVybmV0LWtleS1leGFtcGxlIQ=="
    Write-Host "[OK] .env generated successfully." -ForegroundColor Green
}

# 2. Check Docker
try {
    docker info 2>&1 | Out-Null
} catch {
    Write-Host "[ERROR] Docker is not running! Please start Docker Desktop." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# 3. Launch Docker Stack
Write-Host "[1/3] Starting Docker containers (detached)..." -ForegroundColor Yellow
docker compose up -d --remove-orphans

# 4. Wait for healthy response
Write-Host "[2/3] Waiting for Web (3000) and API (8000) to respond..." -ForegroundColor Yellow
$Ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $web = (Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 2).StatusCode
        $api = (Invoke-WebRequest -Uri "http://localhost:8000/docs" -UseBasicParsing -TimeoutSec 2).StatusCode
        if ($web -eq 200 -and $api -eq 200) {
            $Ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($Ready) {
    Write-Host "[OK] Services are ready!" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Starting browser, services are warming up..." -ForegroundColor Yellow
}

# 5. Open browser
Write-Host "[3/3] Launching web app in default browser..." -ForegroundColor Yellow
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  Capacity Connect is Live!" -ForegroundColor Green
Write-Host "  ------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  * Web App:       http://localhost:3000" -ForegroundColor White
Write-Host "  * API Docs:      http://localhost:8000/docs" -ForegroundColor White
Write-Host "  * Mailpit Inbox: http://localhost:8025" -ForegroundColor White
Write-Host "  * PostgreSQL:    localhost:5432 (Database: capacity_connect)" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Commands:" -ForegroundColor DarkGray
Write-Host "  - To view live logs:    docker compose logs -f" -ForegroundColor DarkGray
Write-Host "  - To stop the stack:    docker compose stop" -ForegroundColor DarkGray
Write-Host ""
