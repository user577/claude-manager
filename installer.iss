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
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "dist\ClaudeManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\icu*.dll"
Type: files; Name: "{app}\_internal\icu*.dll"
; Clear every OpenSSL before copying, so the installed set is exactly what the
; bundle ships. An upgrade otherwise leaves behind the DLLs of whatever OpenSSL
; an older build wrongly picked up off PATH: never loaded (_ssl.pyd binds its
; own by name), but the install directory is on the user PATH, so those orphans
; are what the next build's dependency scan finds. InstallDelete runs before
; [Files], which restores the pair the bundle actually carries.
Type: files; Name: "{app}\_internal\libcrypto-*.dll"
Type: files; Name: "{app}\_internal\libssl-*.dll"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
