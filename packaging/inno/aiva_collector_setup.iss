#define AppName "AIVA Collector"
#define AppVersion "0.2.6rc4"
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
OutputBaseFilename=AIVA-Collector-Setup-v0.2.6-interactive-rc4
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Dirs]
Name: "{commonappdata}\AIVA\Collector"
Name: "{commonappdata}\AIVA\Collector\entrada"
Name: "{commonappdata}\AIVA\Collector\procesados"
Name: "{commonappdata}\AIVA\Collector\rechazados"
Name: "{commonappdata}\AIVA\Collector\procesados\duplicados"
Name: "{commonappdata}\AIVA\Collector\ultimo_summary"
Name: "{commonappdata}\AIVA\Collector\logs"
Name: "{commonappdata}\AIVA\Collector\estado"
Name: "{commonappdata}\AIVA\Collector\estado\queue"
Name: "{commonappdata}\AIVA\Collector\mapeos"
Name: "{commonappdata}\AIVA\Collector\diagnostico"
Name: "{commonappdata}\AIVA\Collector\backups"

[Files]
Source: "..\..\dist\aiva-collector.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\aiva-collector-background.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\windows_runtime\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\windows\config.windows.example.json"; DestDir: "{commonappdata}\AIVA\Collector"; DestName: "config.windows.json"; Flags: onlyifdoesntexist ignoreversion
Source: "..\..\windows\config.windows.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\aiva_collector_windows_installer.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\aiva_collector_windows_exe.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AIVA Collector"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Activar"; Filename: "{app}\activate.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Abrir carpeta de entrada"; Filename: "{app}\open_input_folder.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Prueba sin enviar"; Filename: "{app}\run_dry.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Detectar fuentes sin enviar"; Filename: "{app}\run_discovery_dry.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Reportar fuentes detectadas"; Filename: "{app}\run_discovery_report.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Diagnosticar configuracion"; Filename: "{app}\diagnose_config.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Procesar ahora"; Filename: "{app}\run_auto.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Estado de Cola"; Filename: "{app}\run_queue_status.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Reintentar Pendientes"; Filename: "{app}\run_retry_pending.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Estado conexion"; Filename: "{app}\run_status.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Diagnostico"; Filename: "{app}\collect_diagnostics.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Instalar tarea automatica"; Filename: "{app}\install_scheduled_task.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Quitar tarea automatica"; Filename: "{app}\uninstall_scheduled_task.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Validar configuracion"; Filename: "{app}\run_validate.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Abrir resultados"; Filename: "{app}\open_output_folder.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\AIVA Collector"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo de validacion en el escritorio"; GroupDescription: "Accesos directos adicionales:"; Flags: unchecked

[Run]
Filename: "{app}\install_scheduled_task.bat"; Parameters: "/quiet"; Flags: runhidden waituntilterminated
Filename: "{app}\activate.bat"; Description: "Activar AIVA Collector"; Flags: postinstall skipifsilent nowait
