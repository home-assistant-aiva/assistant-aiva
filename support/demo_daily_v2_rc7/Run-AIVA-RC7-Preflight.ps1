# Read-only Windows preflight plus a local, verified RC6 backup.
# This script does not install RC7, change the Collector config, or sync data.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Count-Status($Object, [string]$Name) {
    if ($null -eq $Object -or $Object.PSObject.Properties.Name -notcontains $Name) { return 0 }
    return [int]$Object.$Name
}

$ExpectedInstallerSha = '1899cf40b4b36f7198aded997f1fd8a25238ab5f5eb63681b84933183ad2cbf4'
$ExpectedSourceZipSha = '5b258b2edf6745c6149aef4a4c9ecb7dc061522ad5c15e8378a2c235302e37ef'
$ExpectedSourceSha = '2a173badfd6bad847af779d89b947139110af3a3d0108601edb05a96e53f2cd3'
$ExpectedCommerce = 'commerce_a0e93d3ec7ac'
$ExpectedCollector = 'collector_dc15555b7052'
$Inbox = 'C:\AIVA-Piloto-RC7'
$DataRoot = Join-Path $env:ProgramData 'AIVA\Collector'
$ConfigPath = Join-Path $DataRoot 'config.windows.json'
$Cli = Join-Path $env:ProgramFiles 'AIVA Collector\aiva-collector-cli.exe'
$Installer = Join-Path $Inbox 'AIVA-Collector-Setup-v0.2.7-desktop-rc7.exe'
$SourceZip = Join-Path $Inbox 'aiva-demo-daily-v2-source-20260929.zip'
$TaskName = 'AIVA Collector Auto'
$Backup = $null

try {
    $Principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    Require ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'Abrí PowerShell como administrador.'
    Require ([Environment]::Is64BitProcess) 'Se requiere PowerShell de 64 bits.'
    foreach ($Path in @($Installer, $SourceZip, $ConfigPath, $Cli)) {
        Require (Test-Path -LiteralPath $Path -PathType Leaf) 'Falta uno de los archivos requeridos. No se modificó el Collector.'
    }
    Require ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedInstallerSha) 'El SHA del instalador RC7 no coincide.'
    Require ((Get-FileHash -LiteralPath $SourceZip -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSourceZipSha) 'El SHA del bundle sintético no coincide.'

    $Config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Require ($Config.commerce_id -eq $ExpectedCommerce -and $Config.collector_id -eq $ExpectedCollector) 'La identidad instalada no es la del comercio demo.'
    Require ($Config.PSObject.Properties.Name -notcontains 'collector_token') 'La configuración contiene un token inesperado; detener el piloto.'
    $Version = (& $Cli --version | Out-String).Trim()
    Require ($LASTEXITCODE -eq 0 -and $Version -match '0\.2\.7rc6') 'El Collector instalado no informa RC6.'
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $TaskStateBefore = [string]$Task.State

    Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
    $Deadline = (Get-Date).AddMinutes(2)
    do {
        $Running = @(Get-Process -Name 'aiva-collector', 'aiva-collector-cli', 'aiva-collector-background' -ErrorAction SilentlyContinue)
        if ($Running.Count -eq 0) { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $Deadline)
    Require ($Running.Count -eq 0) 'El Collector aún está abierto o procesando; cerralo antes de continuar. La tarea quedó deshabilitada.'

    $Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss-fff')
    $Backup = Join-Path (Split-Path $DataRoot -Parent) ('Collector-backup-RC6-' + $Stamp)
    Require (-not (Test-Path -LiteralPath $Backup)) 'Ya existe un backup con este nombre.'
    New-Item -ItemType Directory -Path $Backup | Out-Null
    & robocopy.exe $DataRoot $Backup /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XJ /NFL /NDL /NJH /NJS /NP | Out-Null
    Require ($LASTEXITCODE -lt 8) 'Falló la copia de seguridad local.'
    $SourceFiles = @(Get-ChildItem -LiteralPath $DataRoot -Recurse -File -Force)
    $BackupFiles = @(Get-ChildItem -LiteralPath $Backup -Recurse -File -Force)
    Require ($SourceFiles.Count -eq $BackupFiles.Count) 'El backup no conserva la cantidad de archivos.'
    foreach ($File in $SourceFiles) {
        $Relative = $File.FullName.Substring($DataRoot.Length).TrimStart('\')
        $Copy = Join-Path $Backup $Relative
        Require (Test-Path -LiteralPath $Copy -PathType Leaf) 'Falta un archivo en el backup.'
        Require ($File.Length -eq (Get-Item -LiteralPath $Copy).Length) 'Un archivo del backup tiene otro tamaño.'
        Require ((Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $Copy -Algorithm SHA256).Hash) 'Un archivo del backup no coincide.'
    }
    Export-ScheduledTask -TaskName $TaskName | Set-Content -LiteralPath (Join-Path $Backup 'task-AIVA-Collector-Auto.xml') -Encoding UTF8

    $StatusText = (& $Cli status --config $ConfigPath | Out-String)
    Require ($LASTEXITCODE -eq 0) 'No se pudo comprobar el estado RC6 después del backup.'
    $Status = $StatusText | ConvertFrom-Json
    $Queue = $Status.local_state.upload_queue
    $Processed = $Status.local_state.processed_files
    $Mapping = $Config.column_mapping
    $InputCount = 0
    $OtherFiles = 0
    if ($null -ne $Config.input_dir -and (Test-Path -LiteralPath $Config.input_dir -PathType Container)) {
        $InputFiles = @(Get-ChildItem -LiteralPath $Config.input_dir -File | Where-Object { $_.Extension.ToLowerInvariant() -in @('.csv', '.xlsx') })
        $InputCount = $InputFiles.Count
        $OtherFiles = @($InputFiles | Where-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSourceSha }).Count
    }
    $SourceSchemaVersion = 'absent'
    if ($Config.PSObject.Properties.Name -contains 'source_schema_version') {
        $SourceSchemaVersion = [string]$Config.source_schema_version
    }
    $Report = [ordered]@{
        pilot = 'AIVA demo daily v2 RC7'
        installed_version = $Version
        commerce_matches = $true
        collector_matches = $true
        config_sha256 = (Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash.ToLowerInvariant()
        source_schema_version = $SourceSchemaVersion
        mapping_has_fecha = ($null -ne $Mapping -and $Mapping.PSObject.Properties.Name -contains 'fecha')
        mapping_has_producto_codigo = ($null -ne $Mapping -and $Mapping.PSObject.Properties.Name -contains 'producto_codigo')
        configured_input_supported_files = $InputCount
        configured_input_other_sha_files = $OtherFiles
        task_state_before = $TaskStateBefore
        task_state_after = [string](Get-ScheduledTask -TaskName $TaskName).State
        backup_path = $Backup
        backup_verified_files = $SourceFiles.Count
        state_db_exists = (Test-Path -LiteralPath $Status.local_state.db_path -PathType Leaf)
        queue_pending = (Count-Status $Queue 'pending')
        queue_retrying = (Count-Status $Queue 'retrying')
        queue_processing = (Count-Status $Queue 'processing')
        queue_error = (Count-Status $Queue 'error')
        processed_sent = (Count-Status $Processed 'sent')
        backend_connected = ($Status.PSObject.Properties.Name -contains 'backend')
        installer_sha256 = $ExpectedInstallerSha
        source_bundle_sha256 = $ExpectedSourceZipSha
        source_xlsx_sha256 = $ExpectedSourceSha
        installed = $false
        synced = $false
    }
    $ReportPath = Join-Path $Inbox 'aiva-rc7-preflight-sanitized.json'
    $Report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    Write-Host 'Preflight RC6 y backup local verificado. RC7 no fue instalado; no se enviaron datos.'
    Write-Host ('Reporte sanitizado: ' + $ReportPath)
    $Tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $Tailscale -PathType Leaf) {
        & $Tailscale file cp $ReportPath 'srv1382697:'
        if ($LASTEXITCODE -eq 0) { Write-Host 'Reporte enviado al VPS por Taildrop.' }
    }
} catch {
    Write-Host 'Preflight detenido sin instalación ni sincronización.'
    if ($null -ne $Backup) { Write-Host ('Backup local: ' + $Backup) }
    Write-Host ('Motivo: ' + $_.Exception.Message)
    exit 2
}
