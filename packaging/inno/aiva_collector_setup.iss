#define AppName "AIVA Collector"
#define AppVersion "0.2.7rc2"
#define AppPublisher "AIVA Comercial"
#define AppExeName "aiva-collector.exe"

[Setup]
AppId={{8E61F9E0-4E7F-4CE7-9F4D-A1FA00010051}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\AIVA Collector
DefaultGroupName=AIVA Collector
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=AIVA-Collector-Setup-v0.2.7-desktop-rc2
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Dirs]
Name: "{commonappdata}\AIVA\Collector"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\entrada"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\procesados"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\rechazados"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\procesados\duplicados"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\ultimo_summary"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\logs"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\estado"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\estado\queue"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\mapeos"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\diagnostico"; Permissions: users-modify
Name: "{commonappdata}\AIVA\Collector\backups"; Permissions: users-modify

[Files]
Source: "..\..\dist\aiva-collector.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\aiva-collector-cli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\aiva-collector-background.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\windows_runtime\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\windows\config.windows.example.json"; DestDir: "{commonappdata}\AIVA\Collector"; DestName: "config.windows.json"; Flags: onlyifdoesntexist ignoreversion
Source: "..\..\windows\config.windows.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\aiva_collector_windows_installer.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\aiva_collector_windows_exe.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AIVA Collector"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Soporte\Abrir registros"; Filename: "{sys}\explorer.exe"; Parameters: """{commonappdata}\AIVA\Collector\logs"""
Name: "{group}\Soporte\Generar diagnostico"; Filename: "{app}\collect_diagnostics.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\AIVA Collector"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo de AIVA Collector en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkedonce

[Run]
Filename: "{app}\install_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExeName}"; Description: "Abrir AIVA Collector"; Flags: postinstall skipifsilent nowait runasoriginaluser

[UninstallRun]
Filename: "{app}\uninstall_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated skipifdoesntexist
