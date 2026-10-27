param(
  [string]$PostgresImage = "pgvector/pgvector:pg15",
  [string]$Python = ""
)

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$migrationPath = Join-Path $repositoryRoot "db\migrations"
$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if (-not $docker) {
  throw "Docker is required. Install and start Docker Desktop, then rerun this script."
}
if (-not $Python) {
  $venvPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
  $isolatedPython = Join-Path $env:LOCALAPPDATA "venvs\capacity-connect-api\Scripts\python.exe"
  $Python = if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $venvPython
  } else {
    $isolatedPython
  }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw "The API interpreter was not found at $Python. Create the API virtual environment and install apps/api/requirements-dev.txt first."
}

$containerName = "cc-capacity-connect-auth-test-$([guid]::NewGuid().ToString('N'))"
$databasePassword = [guid]::NewGuid().ToString("N")
$containerId = $null
$containerCreated = $false
$previousTestDatabaseUrl = $env:CAPACITY_CONNECT_TEST_DATABASE_URL

try {
  $containerId = & $docker.Source run --detach `
    --name $containerName `
    --publish "127.0.0.1::5432" `
    --env "POSTGRES_DB=cc_auth_test" `
    --env "POSTGRES_USER=cc_auth_test" `
    --env "POSTGRES_PASSWORD=$databasePassword" `
    --mount "type=bind,source=$migrationPath,target=/docker-entrypoint-initdb.d,readonly" `
    $PostgresImage
  if ($LASTEXITCODE -ne 0 -or -not $containerId) {
    throw "Could not start a disposable PostgreSQL container for auth-flow tests."
  }
  $containerId = $containerId.Trim()
  $containerCreated = $true

  $initializationLog = ""
  $initialized = $false
  for ($attempt = 0; $attempt -lt 180; $attempt++) {
    $initializationLog = (& $docker.Source logs $containerId 2>&1 | ForEach-Object { "$_" }) -join "`n"
    if ($initializationLog.Contains("PostgreSQL init process complete")) {
      $initialized = $true
      break
    }
    $containerStatus = & $docker.Source inspect --format "{{.State.Status}}" $containerId 2>$null
    if ($LASTEXITCODE -ne 0 -or $containerStatus -ne "running") {
      throw "PostgreSQL exited before migrations completed. Container output:`n$initializationLog"
    }
    Start-Sleep -Seconds 1
  }
  if (-not $initialized) {
    throw "PostgreSQL did not finish initializing within 180 seconds. Container output:`n$initializationLog"
  }

  $portMapping = & $docker.Source port $containerId "5432/tcp"
  if ($LASTEXITCODE -ne 0 -or -not $portMapping) {
    throw "Could not resolve the loopback-only PostgreSQL port for the disposable container."
  }
  $hostPort = [int](($portMapping.Trim() -split ":")[-1])
  $env:CAPACITY_CONNECT_TEST_DATABASE_URL = "postgresql://cc_auth_test:$databasePassword@127.0.0.1:$hostPort/cc_auth_test"

  Set-Location -LiteralPath (Join-Path $repositoryRoot "apps\api")
  & $Python -m pytest -q tests/test_auth_flows.py
  if ($LASTEXITCODE -ne 0) {
    throw "Disposable database authentication-flow tests failed."
  }
}
finally {
  if ($null -eq $previousTestDatabaseUrl) {
    Remove-Item Env:\CAPACITY_CONNECT_TEST_DATABASE_URL -ErrorAction SilentlyContinue
  } else {
    $env:CAPACITY_CONNECT_TEST_DATABASE_URL = $previousTestDatabaseUrl
  }
  if ($containerCreated) {
    $containerStatus = & $docker.Source inspect --format "{{.State.Status}}" $containerId 2>$null
    if ($LASTEXITCODE -eq 0 -and $containerStatus -eq "running") {
      & $docker.Source stop $containerId | Out-Null
    }
    & $docker.Source rm --volumes $containerId | Out-Null
  }
}
