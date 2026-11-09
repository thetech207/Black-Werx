; Inno Setup script for Black-Werx (Windows)
; Build: packaging\build-windows.ps1 <version>
;   or:  iscc packaging\blackwerx.iss /DMyAppVersion=1.0.4

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{7C4A9E21-3F5B-4D8A-B6E1-9A2C5D7F0E34}
AppName=Black-Werx
AppVersion={#MyAppVersion}
AppPublisher=thetech207
AppPublisherURL=https://github.com/thetech207/Black-Werx
AppSupportURL=https://github.com/thetech207/Black-Werx/issues
DefaultDirName={autopf}\Black-Werx
DefaultGroupName=Black-Werx
OutputDir=..\dist
OutputBaseFilename=blackwerx_{#MyAppVersion}_win64_setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupIconFile=..\Images\blackwerx-icon.ico
UninstallDisplayIcon={app}\blackwerx.exe
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\blackwerx\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Black-Werx"; Filename: "{app}\blackwerx.exe"
Name: "{autodesktop}\Black-Werx"; Filename: "{app}\blackwerx.exe"; Tasks: desktopicon

[Registry]
; .bwpx file association (per-user, merges into HKCR view)
Root: HKCU; Subkey: "Software\Classes\.bwpx"; ValueType: string; ValueData: "BlackWerx.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\BlackWerx.Project"; ValueType: string; ValueData: "Black-Werx Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\BlackWerx.Project\DefaultIcon"; ValueType: string; ValueData: "{app}\blackwerx.exe,0"
Root: HKCU; Subkey: "Software\Classes\BlackWerx.Project\shell\open\command"; ValueType: string; ValueData: """{app}\blackwerx.exe"" ""%1"""

[Run]
Filename: "{app}\blackwerx.exe"; Description: "Launch Black-Werx"; Flags: nowait postinstall skipifsilent
