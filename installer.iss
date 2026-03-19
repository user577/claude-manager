#define MyAppName "Claude Manager"
#define MyAppExeName "ClaudeManager.exe"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{B7E3F2A1-8C4D-4E5F-9A6B-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\ClaudeManager
DefaultGroupName={#MyAppName}
OutputDir=Output
OutputBaseFilename=ClaudeManager-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\ClaudeManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
