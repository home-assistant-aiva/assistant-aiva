#define AppName "AIVA Collector"
#define AppVersion "0.1.0"
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
OutputBaseFilename=AIVA-Collector-Setup-v0.1.0
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Dirs]
Name: "C:\AIVA_Comercio"
Name: "C:\AIVA_Comercio\entrada"
Name: "C:\AIVA_Comercio\procesados"
Name: "C:\AIVA_Comercio\error"
Name: "C:\AIVA_Comercio\output"
Name: "C:\AIVA_Comercio\logs"
Name: "C:\AIVA_Comercio\state"
Name: "C:\AIVA_Comercio\diagnostico"

[Files]
Source: "..\..\dist\aiva-collector.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\windows_runtime\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\windows\config.windows.example.json"; DestDir: "C:\AIVA_Comercio"; DestName: "config.local.json"; Flags: onlyifdoesntexist ignoreversion
Source: "..\..\windows\config.windows.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\aiva_collector_windows_installer.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\docs\aiva_collector_windows_exe.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AIVA Collector - Validar configuracion"; Filename: "{app}\run_validate.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Prueba sin enviar"; Filename: "{app}\run_dry.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Estado conexion"; Filename: "{app}\run_status.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Enviar al servidor"; Filename: "{app}\run_send.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Diagnostico"; Filename: "{app}\collect_diagnostics.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Abrir carpeta de entrada"; Filename: "{app}\open_input_folder.bat"; WorkingDir: "{app}"
Name: "{group}\AIVA Collector - Abrir resultados"; Filename: "{app}\open_output_folder.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\AIVA Collector - Validar configuracion"; Filename: "{app}\run_validate.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo de validacion en el escritorio"; GroupDescription: "Accesos directos adicionales:"; Flags: unchecked

[Run]
Filename: "{app}\open_input_folder.bat"; Description: "Abrir carpeta de entrada"; Flags: postinstall skipifsilent nowait
