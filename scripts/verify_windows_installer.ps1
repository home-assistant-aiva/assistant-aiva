param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedVersion,
  [Parameter(Mandatory = $true)]
  [string]$ExpectedPublicVersion,
  [Parameter(Mandatory = $true)]
  [string]$DefenderEvidencePath
)

$ErrorActionPreference = "Stop"
$TaskName = "AIVA Collector Auto"
$InstallDir = Join-Path $env:RUNNER_TEMP "AIVA Collector Upgrade Test"
$DataRoot = Join-Path $env:ProgramData "AIVA\Collector"
$SourceRoot = Join-Path $env:RUNNER_TEMP "AIVA Collector Read Only Source"
$EvidencePath = Join-Path (Resolve-Path ".\dist") "windows-installer-verification.json"
$Installer = (Resolve-Path $InstallerPath).Path
$ExpectedInstallerName = "AIVA-Collector-Setup-v$ExpectedPublicVersion.exe"
$BuildCommit = [string]$env:AIVA_BUILD_COMMIT
$BuiltAppDir = Join-Path (Resolve-Path ".\dist") "aiva-collector"

function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

function Assert-PreservedFiles([hashtable]$ExpectedHashes) {
  foreach ($entry in $ExpectedHashes.GetEnumerator()) {
    Assert-True (Test-Path -LiteralPath $entry.Key) "La actualizacion elimino un archivo persistente: $($entry.Key)"
    $actual = (Get-FileHash -LiteralPath $entry.Key -Algorithm SHA256).Hash
    Assert-True ($actual -eq $entry.Value) "La actualizacion modifico un archivo persistente: $($entry.Key)"
  }
}

function Remove-ScheduledTask {
  & schtasks.exe /Delete /TN $TaskName /F *> $null
  $global:LASTEXITCODE = 0
}

function Stop-InstalledCollectorProcesses {
  $processNames = @("aiva-collector", "aiva-collector-cli", "aiva-collector-background")
  foreach ($name in $processNames) {
    foreach ($process in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
      & taskkill.exe /PID $process.Id /T /F *> $null
    }
  }

  $deadline = [DateTime]::UtcNow.AddSeconds(10)
  do {
    $remaining = @(
      foreach ($name in $processNames) {
        Get-Process -Name $name -ErrorAction SilentlyContinue
      }
    )
    if ($remaining.Count -eq 0) { return }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)

  throw "Quedaron procesos Collector activos: $($remaining.Id -join ', ')."
}

function Reset-TestInstallation {
  Remove-ScheduledTask
  Stop-InstalledCollectorProcesses
  if (Test-Path $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
  if (Test-Path $DataRoot) { Remove-Item -LiteralPath $DataRoot -Recurse -Force }
}

function Invoke-Installer {
  $arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=`"$InstallDir`"")
  $process = Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru
  Assert-True ($process.ExitCode -eq 0) "El instalador termino con codigo $($process.ExitCode)."
}

function Assert-ScheduledTask {
  $taskXml = (& schtasks.exe /Query /TN $TaskName /XML 2>&1) -join "`n"
  Assert-True ($LASTEXITCODE -eq 0) "No se creo la tarea programada $TaskName."
  Assert-True ($taskXml -match "aiva-collector-background\.exe") "La tarea no usa el runner background."
  Assert-True ($taskXml -match "run-auto") "La tarea no ejecuta run-auto."
  Assert-True ($taskXml -match "config\.windows\.json") "La tarea no referencia la configuracion persistente."
  Assert-True ($taskXml -notmatch "token") "La tarea expone un token en sus argumentos."
}

function Assert-TaskRemoved {
  & schtasks.exe /Query /TN $TaskName *> $null
  Assert-True ($LASTEXITCODE -ne 0) "La tarea programada sobrevivio a la desinstalacion."
}

function Assert-InstalledBinaries {
  foreach ($name in @("aiva-collector.exe", "aiva-collector-cli.exe", "aiva-collector-background.exe")) {
    $installed = Join-Path $InstallDir $name
    $built = Join-Path $BuiltAppDir $name
    Assert-True (Test-Path $installed) "Falta binario instalado: $name"
    Assert-True ((Get-FileHash $installed -Algorithm SHA256).Hash -eq (Get-FileHash $built -Algorithm SHA256).Hash) "El binario instalado no coincide con el build actual: $name"
  }
  $builtFiles = @(Get-ChildItem -LiteralPath $BuiltAppDir -Recurse -File)
  Assert-True ($builtFiles.Count -gt 3) "El bundle onedir no contiene dependencias compartidas."
  foreach ($built in $builtFiles) {
    $relative = $built.FullName.Substring($BuiltAppDir.Length).TrimStart('\')
    $installed = Join-Path $InstallDir $relative
    Assert-True (Test-Path -LiteralPath $installed) "Falta archivo onedir instalado: $relative"
    Assert-True ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $built.FullName -Algorithm SHA256).Hash) "El archivo onedir instalado no coincide con el build: $relative"
  }
  Assert-True (Test-Path (Join-Path $InstallDir "unins000.exe")) "No existe el desinstalador."
}

function Assert-CollectorRuntime {
  $desktop = Join-Path $InstallDir "aiva-collector.exe"
  $cli = Join-Path $InstallDir "aiva-collector-cli.exe"
  $version = (& $cli --version 2>&1 | Out-String).Trim()
  Assert-True ($LASTEXITCODE -eq 0) "--version fallo."
  Assert-True ($version -eq $ExpectedVersion) "Version inesperada: $version"

  $selfCheck = Start-Process -FilePath $desktop -ArgumentList "--self-check" -Wait -PassThru
  Assert-True ($selfCheck.ExitCode -eq 0) "Desktop --self-check fallo con $($selfCheck.ExitCode)."

  $gui = Start-Process -FilePath $desktop -PassThru
  Start-Sleep -Seconds 4
  $gui.Refresh()
  Assert-True (-not $gui.HasExited) "La interfaz Desktop/Tkinter no permanecio abierta."
  Stop-InstalledCollectorProcesses
}

function Invoke-Uninstaller {
  $uninstaller = Join-Path $InstallDir "unins000.exe"
  Assert-True (Test-Path $uninstaller) "No existe unins000.exe."
  $process = Start-Process -FilePath $uninstaller -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
  Assert-True ($process.ExitCode -eq 0) "La desinstalacion termino con codigo $($process.ExitCode)."
  Assert-TaskRemoved
  Assert-True (-not (Test-Path (Join-Path $InstallDir "aiva-collector.exe"))) "La desinstalacion dejo el ejecutable Desktop."
}

Assert-True ((Split-Path $Installer -Leaf) -eq $ExpectedInstallerName) "Nombre de instalador inesperado."
$signature = Get-AuthenticodeSignature -FilePath $Installer
$signatureStatus = [string]$signature.Status
if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::NotSigned) {
  Write-Warning "Instalador sin firma digital; Windows SmartScreen puede mostrar una advertencia durante la prueba."
} elseif ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
  throw "Firma Authenticode invalida: $signatureStatus"
}

$evidence = [ordered]@{
  installer = $ExpectedInstallerName
  expected_version = $ExpectedVersion
  build_commit = $BuildCommit.Trim().ToLowerInvariant()
  clean_install = $false
  previous_version_update = $false
  config_preserved = $false
  activation_preserved = $false
  token_preserved = $false
  state_preserved = $false
  queue_preserved = $false
  mappings_preserved = $false
  logs_preserved = $false
  source_folder_preserved = $false
  self_check = $false
  tkinter_desktop_started = $false
  scheduled_task = $false
  binaries_replaced = $false
  no_database_in_installed_files = $false
  uninstall = $false
  signature_status = $signatureStatus
  defender_status = "pending"
  defender_available = $false
}

Assert-True ($evidence.build_commit -match '^[0-9a-f]{40}$') "AIVA_BUILD_COMMIT no identifica el commit compilado."

try {
  Reset-TestInstallation

  Invoke-Installer
  Assert-InstalledBinaries
  Assert-CollectorRuntime
  Assert-ScheduledTask
  $cleanConfig = Get-Content -Raw -LiteralPath (Join-Path $DataRoot "config.windows.json") | ConvertFrom-Json
  Assert-True ($null -eq $cleanConfig.collector_token) "La configuracion del instalador contiene collector_token."
  $evidence.clean_install = $true
  $evidence.self_check = $true
  $evidence.tkinter_desktop_started = $true
  $evidence.scheduled_task = $true
  Invoke-Uninstaller

  if (Test-Path $DataRoot) { Remove-Item -LiteralPath $DataRoot -Recurse -Force }
  if (Test-Path $SourceRoot) { Remove-Item -LiteralPath $SourceRoot -Recurse -Force }
  New-Item -ItemType Directory -Force -Path `
    $InstallDir, `
    $DataRoot, `
    $SourceRoot, `
    (Join-Path $DataRoot "estado"), `
    (Join-Path $DataRoot "estado\queue"), `
    (Join-Path $DataRoot "mapeos"), `
    (Join-Path $DataRoot "logs") | Out-Null
  $legacyConfig = @{
    collector_version = "0.2.7rc1"
    backend_url = "https://backend.invalid"
    commerce_id = "commerce-simulated-rc1"
    collector_id = "collector-simulated-rc1"
    collector_token_env = "AIVA_COLLECTOR_TOKEN"
    input_dir = $SourceRoot
    processed_dir = (Join-Path $DataRoot "procesados")
    error_dir = (Join-Path $DataRoot "rechazados")
    output_dir = (Join-Path $DataRoot "ultimo_summary")
    state_dir = (Join-Path $DataRoot "estado")
    log_file = (Join-Path $DataRoot "logs\collector.log")
    column_mapping = @{}
  } | ConvertTo-Json -Depth 10
  $configPath = Join-Path $DataRoot "config.windows.json"
  [System.IO.File]::WriteAllText($configPath, $legacyConfig, [System.Text.UTF8Encoding]::new($false))
  $tokenMarker = "SIMULATED-RC1-TOKEN"
  $fakeDpapi = "DPAPI:" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($tokenMarker))
  $tokenPath = Join-Path $DataRoot "estado\collector.token"
  [System.IO.File]::WriteAllText($tokenPath, $fakeDpapi, [System.Text.UTF8Encoding]::new($false))
  $statePath = Join-Path $DataRoot "estado\collector-state.json"
  $queuePath = Join-Path $DataRoot "estado\queue\pending.json"
  $mappingPath = Join-Path $DataRoot "mapeos\mapping.json"
  $logPath = Join-Path $DataRoot "logs\collector.log"
  $sourcePath = Join-Path $SourceRoot "ventas-sinteticas.csv"
  [System.IO.File]::WriteAllText($statePath, '{"state":"preserve"}', [System.Text.UTF8Encoding]::new($false))
  [System.IO.File]::WriteAllText($queuePath, '{"queue":"preserve"}', [System.Text.UTF8Encoding]::new($false))
  [System.IO.File]::WriteAllText($mappingPath, '{"mapping":"preserve"}', [System.Text.UTF8Encoding]::new($false))
  [System.IO.File]::WriteAllText($logPath, 'PREVIOUS-VERSION-LOG', [System.Text.UTF8Encoding]::new($false))
  [System.IO.File]::WriteAllText($sourcePath, "producto,cantidad`nPrueba,1", [System.Text.UTF8Encoding]::new($false))
  $persistentHashes = @{}
  foreach ($path in @($configPath, $tokenPath, $statePath, $queuePath, $mappingPath, $logPath, $sourcePath)) {
    $persistentHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  }
  foreach ($name in @("aiva-collector.exe", "aiva-collector-cli.exe", "aiva-collector-background.exe")) {
    Set-Content -LiteralPath (Join-Path $InstallDir $name) -Value "RC1-OLD-BINARY" -NoNewline
  }

  Invoke-Installer
  Assert-PreservedFiles $persistentHashes
  $preservedConfig = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
  Assert-True ($preservedConfig.commerce_id -eq "commerce-simulated-rc1") "La actualizacion modifico la activacion previa."
  Assert-True ($preservedConfig.collector_id -eq "collector-simulated-rc1") "La actualizacion modifico el Collector activado."
  Assert-InstalledBinaries
  Assert-CollectorRuntime
  Assert-ScheduledTask
  $databases = @(Get-ChildItem -LiteralPath $InstallDir -Recurse -File | Where-Object { $_.Extension -in @(".db", ".sqlite", ".sqlite3") })
  Assert-True ($databases.Count -eq 0) "El instalador incluyo una base de datos."
  $evidence.previous_version_update = $true
  $evidence.config_preserved = $true
  $evidence.activation_preserved = $true
  $evidence.token_preserved = $true
  $evidence.state_preserved = $true
  $evidence.queue_preserved = $true
  $evidence.mappings_preserved = $true
  $evidence.logs_preserved = $true
  $evidence.source_folder_preserved = $true
  $evidence.binaries_replaced = $true
  $evidence.no_database_in_installed_files = $true
  & (Join-Path $PSScriptRoot "verify_windows_defender.ps1") -ScanPath @($BuiltAppDir, $Installer, $InstallDir) -EvidencePath $DefenderEvidencePath -BuildCommit $BuildCommit
  $defenderEvidence = Get-Content -Raw -LiteralPath $DefenderEvidencePath | ConvertFrom-Json
  $evidence.defender_status = [string]$defenderEvidence.status
  $evidence.defender_available = [bool]$defenderEvidence.available
  Invoke-Uninstaller
  Assert-PreservedFiles $persistentHashes
  $evidence.uninstall = $true
  $evidence | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $EvidencePath -Encoding utf8
  Get-Content -Raw -LiteralPath $EvidencePath
} finally {
  Remove-ScheduledTask
  Stop-InstalledCollectorProcesses
  if (Test-Path $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
  if (Test-Path $DataRoot) { Remove-Item -LiteralPath $DataRoot -Recurse -Force }
  if (Test-Path $SourceRoot) { Remove-Item -LiteralPath $SourceRoot -Recurse -Force }
}
