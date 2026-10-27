param(
  [string]$PostgresImage = "pgvector/pgvector:pg15"
)

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$migrationPath = Join-Path $repositoryRoot "db\migrations"
$migrationFiles = @(Get-ChildItem -LiteralPath $migrationPath -File -Filter "*.sql" | Sort-Object Name)
$docker = Get-Command docker.exe -ErrorAction SilentlyContinue

if (-not $docker) {
  throw "Docker is required. Install and start Docker Desktop, then rerun this script."
}
if ($migrationFiles.Count -eq 0) {
  throw "No numbered database migrations were found in $migrationPath."
}

for ($index = 0; $index -lt $migrationFiles.Count; $index++) {
  $expectedPrefix = "{0:D3}_" -f ($index + 1)
  if (-not $migrationFiles[$index].Name.StartsWith($expectedPrefix)) {
    throw "Migration order is incomplete at $expectedPrefix. Found $($migrationFiles[$index].Name)."
  }
}

$imageId = & $docker.Source image inspect --format "{{.Id}}" $PostgresImage 2>$null
if ($LASTEXITCODE -ne 0 -or -not $imageId) {
  throw "Image '$PostgresImage' is unavailable. Pull the configured image, then rerun: docker pull $PostgresImage"
}

$tablePattern = '(?im)^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[A-Za-z_][A-Za-z0-9_]*\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\('
$expectedTables = @(
  foreach ($file in $migrationFiles) {
    $contents = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($match in [regex]::Matches($contents, $tablePattern)) {
      $match.Groups[1].Value.ToLowerInvariant()
    }
  }
) | Sort-Object -Unique

$containerName = "cc-capacity-connect-migration-$([guid]::NewGuid().ToString('N'))"
$containerId = $null
$containerCreated = $false

try {
  $containerId = & $docker.Source run --detach `
    --name $containerName `
    --network none `
    --env "POSTGRES_DB=cc_migration_check" `
    --env "POSTGRES_USER=cc_migration_check" `
    --env "POSTGRES_PASSWORD=temporary-migration-smoke-test" `
    --mount "type=bind,source=$migrationPath,target=/docker-entrypoint-initdb.d,readonly" `
    $PostgresImage
  if ($LASTEXITCODE -ne 0 -or -not $containerId) {
    throw "Could not start the disposable PostgreSQL container for $migrationPath."
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
      throw "PostgreSQL exited before all migrations completed. Container output:`n$initializationLog"
    }

    Start-Sleep -Seconds 1
  }
  if (-not $initialized) {
    throw "PostgreSQL did not finish initializing all migrations within 180 seconds. Container output:`n$initializationLog"
  }

  $migrationPrefix = "/docker-entrypoint-initdb.d/"
  foreach ($file in $migrationFiles) {
    if (-not $initializationLog.Contains("$migrationPrefix$($file.Name)")) {
      throw "PostgreSQL initialization did not confirm $($file.Name). Container output:`n$initializationLog"
    }
  }

  $tableList = & $docker.Source exec $containerId psql `
    --no-psqlrc `
    --set ON_ERROR_STOP=1 `
    --username cc_migration_check `
    --dbname cc_migration_check `
    --tuples-only `
    --no-align `
    --command "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables WHERE schemaname='public'"
  if ($LASTEXITCODE -ne 0) {
    throw "Could not read the initialized schema. Container output:`n$initializationLog"
  }

  $actualTables = @($tableList.Trim().Split(",") | Where-Object { $_ } | Sort-Object -Unique)
  $missingTables = @($expectedTables | Where-Object { $_ -notin $actualTables })
  if ($missingTables.Count -gt 0) {
    throw "Migrations finished, but expected tables are missing: $($missingTables -join ', ')."
  }

  $vectorExtension = & $docker.Source exec $containerId psql `
    --no-psqlrc `
    --set ON_ERROR_STOP=1 `
    --username cc_migration_check `
    --dbname cc_migration_check `
    --tuples-only `
    --no-align `
    --command "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
  if ($LASTEXITCODE -ne 0 -or $vectorExtension.Trim() -ne "t") {
    throw "The configured vector extension is missing from the initialized database."
  }

  Write-Output "PASS: all $($migrationFiles.Count) contiguous, numbered migrations completed in order."
  Write-Output "PASS: all $($expectedTables.Count) tables declared by the migrations exist."
  Write-Output "PASS: pgvector extension is installed."
  $roadmapConstraints = & $docker.Source exec $containerId psql `
    --no-psqlrc `
    --set ON_ERROR_STOP=1 `
    --username cc_migration_check `
    --dbname cc_migration_check `
    --tuples-only `
    --no-align `
    --command "SELECT string_agg(pg_get_constraintdef(oid), ';' ORDER BY conname) FROM pg_constraint WHERE conrelid='public.roadmap_milestones'::regclass"
  if ($LASTEXITCODE -ne 0 -or
      -not $roadmapConstraints.Contains("PRIMARY KEY (id)") -or
      -not $roadmapConstraints.Contains("UNIQUE (roadmap_id, step_order)")) {
    throw "The roadmap milestones ID primary key and unique roadmap/step constraint were not initialized correctly."
  }
  Write-Output "PASS: roadmap milestone primary-key and unique-step constraints are valid."
  Write-Output "PASS: migrations were mounted read-only into a network-isolated disposable database."
  Write-Output "PASS: the persistent Compose database and volume were not used."
}
finally {
  if ($containerCreated) {
    $containerStatus = & $docker.Source inspect --format "{{.State.Status}}" $containerId 2>$null
    if ($LASTEXITCODE -eq 0 -and $containerStatus -eq "running") {
      & $docker.Source stop $containerId | Out-Null
    }
    & $docker.Source rm --volumes $containerId | Out-Null
  }
}
