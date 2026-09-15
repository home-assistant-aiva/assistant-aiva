param(
  [Parameter(Mandatory = $true)]
  [string[]]$ScanPath,
  [Parameter(Mandatory = $true)]
  [string]$EvidencePath,
  [string]$BuildCommit = [string]$env:AIVA_BUILD_COMMIT
)

$ErrorActionPreference = "Stop"
$resolvedTargets = @(
  foreach ($target in $ScanPath) {
    if (-not (Test-Path -LiteralPath $target)) {
      throw "Falta objetivo requerido para el escaneo Defender: $(Split-Path $target -Leaf)"
    }
    (Resolve-Path -LiteralPath $target).Path
  }
)

if ($BuildCommit -notmatch '^[0-9a-fA-F]{40}$') {
  throw "BuildCommit no identifica el commit compilado."
}

$authenticodeFiles = @(
  foreach ($target in $resolvedTargets) {
    if (Test-Path -LiteralPath $target -PathType Leaf) {
      if ([IO.Path]::GetExtension($target) -ieq ".exe") {
        Get-Item -LiteralPath $target
      }
    } else {
      Get-ChildItem -LiteralPath $target -Recurse -File |
        Where-Object {
          $_.Name -in @(
            "aiva-collector.exe",
            "aiva-collector-cli.exe",
            "aiva-collector-background.exe"
          )
        }
    }
  }
)
$authenticode = @(
  foreach ($file in $authenticodeFiles | Sort-Object FullName -Unique) {
    $signature = Get-AuthenticodeSignature -FilePath $file.FullName
    [ordered]@{
      file = $file.Name
      status = [string]$signature.Status
    }
  }
)

$evidence = [ordered]@{
  provider = "Microsoft Defender Antivirus"
  build_commit = $BuildCommit.ToLowerInvariant()
  created_at = [DateTime]::UtcNow.ToString("o")
  available = $false
  status = "unavailable"
  unavailable_reason = $null
  definition_update = "not_attempted"
  engine_version = $null
  product_version = $null
  signature_version = $null
  signature_updated_at = $null
  am_running_mode = $null
  targets_scanned = @($resolvedTargets | ForEach-Object { Split-Path $_ -Leaf })
  scan_count = 0
  new_threat_detections = 0
  detection_events = 0
  threat_ids = @()
  authenticode = $authenticode
}

function Write-Evidence {
  $parent = Split-Path -Parent $EvidencePath
  if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
  $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $EvidencePath -Encoding utf8
  Get-Content -Raw -LiteralPath $EvidencePath
}

if (
  -not (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue) -or
  -not (Get-Command Start-MpScan -ErrorAction SilentlyContinue) -or
  -not (Get-Command Get-MpThreatDetection -ErrorAction SilentlyContinue)
) {
  $evidence.unavailable_reason = "Defender PowerShell cmdlets are unavailable on the runner"
  Write-Evidence
  return
}

try {
  $status = Get-MpComputerStatus
  $evidence.engine_version = [string]$status.AMEngineVersion
  $evidence.product_version = [string]$status.AMProductVersion
  $evidence.signature_version = [string]$status.AntivirusSignatureVersion
  if ($null -ne $status.AntivirusSignatureLastUpdated) {
    $evidence.signature_updated_at = ([DateTime]$status.AntivirusSignatureLastUpdated).ToUniversalTime().ToString("o")
  }
  $evidence.am_running_mode = [string]$status.AMRunningMode
  $evidence.available = [bool]($status.AMServiceEnabled -and $status.AntivirusEnabled)
  if (-not $evidence.available) {
    $evidence.unavailable_reason = "Defender antivirus engine is not enabled on the runner"
    Write-Evidence
    return
  }

  if (Get-Command Update-MpSignature -ErrorAction SilentlyContinue) {
    try {
      Update-MpSignature -UpdateSource MicrosoftUpdateServer
      $evidence.definition_update = "success"
    } catch {
      $evidence.definition_update = "failed"
    }
  } else {
    $evidence.definition_update = "cmdlet_unavailable"
  }

  $status = Get-MpComputerStatus
  $evidence.signature_version = [string]$status.AntivirusSignatureVersion
  if ($null -ne $status.AntivirusSignatureLastUpdated) {
    $evidence.signature_updated_at = ([DateTime]$status.AntivirusSignatureLastUpdated).ToUniversalTime().ToString("o")
  }
  $beforeIds = @(
    Get-MpThreatDetection -ErrorAction SilentlyContinue |
      ForEach-Object { [string]$_.DetectionID }
  )
  $scanStarted = Get-Date
  foreach ($target in $resolvedTargets) {
    Start-MpScan -ScanType CustomScan -ScanPath $target
    $evidence.scan_count += 1
  }
  $after = @(Get-MpThreatDetection -ErrorAction SilentlyContinue)
  $newThreats = @(
    $after | Where-Object {
      ([string]$_.DetectionID -notin $beforeIds) -or
      ($null -ne $_.InitialDetectionTime -and $_.InitialDetectionTime -ge $scanStarted)
    }
  )
  $events = @(
    Get-WinEvent -FilterHashtable @{
      LogName = "Microsoft-Windows-Windows Defender/Operational"
      Id = 1116
      StartTime = $scanStarted
    } -ErrorAction SilentlyContinue
  )
  $evidence.new_threat_detections = $newThreats.Count
  $evidence.detection_events = $events.Count
  $evidence.threat_ids = @(
    $newThreats |
      ForEach-Object { [string]$_.ThreatID } |
      Where-Object { $_ } |
      Sort-Object -Unique
  )
  if ($newThreats.Count -gt 0 -or $events.Count -gt 0) {
    $evidence.status = "detected"
    Write-Evidence
    throw "Microsoft Defender detecto una amenaza en los artefactos Windows."
  }
  $evidence.status = "clean"
  Write-Evidence
} catch {
  if ($evidence.status -eq "detected") {
    throw
  }
  $evidence.available = $false
  $evidence.status = "unavailable"
  $evidence.unavailable_reason = "Defender scan could not complete on the hosted runner"
  Write-Evidence
}
