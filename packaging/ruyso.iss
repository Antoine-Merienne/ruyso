; Inno Setup recipe for the Windows installer. Run by packaging/package.sh:
;
;   iscc /DAppVersion=0.1.0 packaging\ruyso.iss
;
; Reads dist\ruyso\ (what PyInstaller wrote), writes out\.
; Per-user install by default, so there is no admin prompt.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: it is how an upgrade finds the previous install.
AppId={{928BA4D2-1B2A-41EB-8F4D-1D99E336A8EC}
AppName=Ruyso
AppVersion={#AppVersion}
AppPublisher=Antoine Merienne
AppPublisherURL=https://github.com/Antoine-Merienne/ruyso
DefaultDirName={autopf}\Ruyso
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\out
OutputBaseFilename=Ruyso-Windows-x64-Setup
SetupIconFile=icons\icon.ico
UninstallDisplayIcon={app}\ruyso.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ruyso\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Ruyso"; Filename: "{app}\ruyso.exe"
Name: "{autodesktop}\Ruyso"; Filename: "{app}\ruyso.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ruyso.exe"; Description: "{cm:LaunchProgram,Ruyso}"; Flags: nowait postinstall skipifsilent
