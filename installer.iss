; PBI Doc Generator - Inno Setup Script
; Run with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

[Setup]
AppName=PBI Doc Generator
AppVersion=0.2-beta
AppPublisher=Rien Scheerlinck
AppPublisherURL=https://github.com/djrien-ai/pbi-doc-generator
AppSupportURL=https://github.com/djrien-ai/pbi-doc-generator/issues
DefaultDirName={autopf}\PBI Doc Generator
DefaultGroupName=PBI Doc Generator
OutputBaseFilename=PBI_Doc_Generator_Setup_v0.2-beta
OutputDir=installer_output
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\PBI_Doc_Generator.exe

[Files]
Source: "dist\PBI_Doc_Generator_v0.2.1.exe"; DestDir: "{app}"; DestName: "PBI_Doc_Generator.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\PBI Doc Generator"; Filename: "{app}\PBI_Doc_Generator.exe"
Name: "{group}\Uninstall PBI Doc Generator"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PBI Doc Generator"; Filename: "{app}\PBI_Doc_Generator.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\PBI_Doc_Generator.exe"; Description: "Launch PBI Doc Generator"; Flags: nowait postinstall skipifsilent
