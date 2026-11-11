#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#ifndef AppSource
  #define AppSource "dist\MSFSBuilder"
#endif
#ifndef OutputDir
  #define OutputDir "output"
#endif

[Setup]
AppId={{DC7C8B8E-E8C6-4890-B788-193723B427D9}
AppName=MSFS Model Builder
AppVersion={#AppVersion}
AppVerName=MSFS Model Builder {#AppVersion}
DefaultDirName={localappdata}\Programs\MSFS Model Builder
DefaultGroupName=MSFS Model Builder
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename=MSFSModelBuilder-{#AppVersion}-Setup
UninstallDisplayIcon={app}\MSFSBuilder.exe
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MSFS Model Builder"; Filename: "{app}\MSFSBuilder.exe"
Name: "{group}\Руководство пользователя"; Filename: "{app}\docs\USER_MANUAL_RU.html"
Name: "{group}\Удалить MSFS Model Builder"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MSFS Model Builder"; Filename: "{app}\MSFSBuilder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MSFSBuilder.exe"; Parameters: "{code:GetConfigParameters}"; StatusMsg: "Сохранение выбранных путей..."; Flags: runhidden waituntilterminated; Check: HasConfiguration
Filename: "{app}\MSFSBuilder.exe"; Description: "Запустить MSFS Model Builder"; Flags: nowait postinstall skipifsilent

[Code]
var
  PackagesPage: TInputQueryWizardPage;
  BlenderPage: TInputQueryWizardPage;
  PackagesBrowse, BlenderBrowse: TNewButton;

procedure BrowsePackages(Sender: TObject);
var
  Folder: String;
begin
  Folder := PackagesPage.Values[0];
  if BrowseForFolder('Каталог MSFS или самолётов', Folder, False) then
    PackagesPage.Values[0] := Folder;
end;

procedure BrowseBlender(Sender: TObject);
var
  FileName: String;
begin
  FileName := BlenderPage.Values[0];
  if GetOpenFileName('Выберите blender.exe', FileName, '', 'Blender|blender.exe', 'exe') then
    BlenderPage.Values[0] := FileName;
end;

procedure InitializeWizard();
begin
  PackagesPage := CreateInputQueryPage(wpSelectDir,
    'Каталог пакетов Microsoft Flight Simulator 2020',
    'Необязательно: укажите Packages, Community или папку распакованного самолёта.',
    'Программа также ищет MSFS по UserCfg.opt текущего пользователя. Если каталог неизвестен, оставьте поле пустым и выберите его позднее в программе.');
  PackagesPage.Add('Каталог MSFS или самолётов:', False);
  PackagesPage.Edits[0].Width := PackagesPage.Edits[0].Width - ScaleX(90);
  PackagesBrowse := TNewButton.Create(WizardForm);
  PackagesBrowse.Parent := PackagesPage.Surface;
  PackagesBrowse.Left := PackagesPage.Edits[0].Left + PackagesPage.Edits[0].Width + ScaleX(10);
  PackagesBrowse.Top := PackagesPage.Edits[0].Top;
  PackagesBrowse.Width := ScaleX(80);
  PackagesBrowse.Height := PackagesPage.Edits[0].Height;
  PackagesBrowse.Caption := 'Обзор...';
  PackagesBrowse.OnClick := @BrowsePackages;
  BlenderPage := CreateInputQueryPage(PackagesPage.ID,
    'Blender',
    'Необязательно: выберите blender.exe.',
    'Blender устанавливается отдельно. Программа использует его для сборки .blend и не требует отдельной установки Python. Путь можно изменить в программе.');
  BlenderPage.Add('Blender:', False);
  BlenderPage.Edits[0].Width := BlenderPage.Edits[0].Width - ScaleX(90);
  BlenderBrowse := TNewButton.Create(WizardForm);
  BlenderBrowse.Parent := BlenderPage.Surface;
  BlenderBrowse.Left := BlenderPage.Edits[0].Left + BlenderPage.Edits[0].Width + ScaleX(10);
  BlenderBrowse.Top := BlenderPage.Edits[0].Top;
  BlenderBrowse.Width := ScaleX(80);
  BlenderBrowse.Height := BlenderPage.Edits[0].Height;
  BlenderBrowse.Caption := 'Обзор...';
  BlenderBrowse.OnClick := @BrowseBlender;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = PackagesPage.ID) and (PackagesPage.Values[0] <> '') and
     not DirExists(PackagesPage.Values[0]) then
  begin
    MsgBox('Указанный каталог не существует. Выберите существующую папку или оставьте поле пустым.', mbError, MB_OK);
    Result := False;
  end;
  if (CurPageID = BlenderPage.ID) and (BlenderPage.Values[0] <> '') and
     not FileExists(BlenderPage.Values[0]) then
  begin
    MsgBox('Файл Blender не найден. Выберите blender.exe или оставьте поле пустым.', mbError, MB_OK);
    Result := False;
  end;
end;

function HasConfiguration(): Boolean;
begin
  Result := (PackagesPage.Values[0] <> '') or (BlenderPage.Values[0] <> '');
end;

function GetConfigParameters(Param: String): String;
begin
  Result := '--configure-only';
  if PackagesPage.Values[0] <> '' then
    Result := Result + ' --configure-msfs ' + AddQuotes(PackagesPage.Values[0]);
  if BlenderPage.Values[0] <> '' then
    Result := Result + ' --configure-blender ' + AddQuotes(BlenderPage.Values[0]);
end;
