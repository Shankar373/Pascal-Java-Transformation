"""A realistic, deterministic enterprise Delphi estate for Stage 1 tests.

``ENTERPRISE_APP`` maps POSIX relative paths to file content.  The tree is
small but exercises every Stage 1 discovery domain on purpose:

* one VCL application (``ERPSystem.dpr``) plus one design-time package;
* Delphi project metadata (``.dproj``) and a ``dcc32.cfg`` compiler config;
* FireDAC / Oracle data access, a SQL schema file and a connection string
  that contains a **password the pipeline must redact**;
* Indy HTTP, a SOAP client, COM/OLE automation, a ``TService`` and an
  FTP/SMTP use;
* third-party libraries: FastReport (absent), DevExpress (absent), JEDI
  (bundled as source under ``lib/jedi``);
* runtime dependencies: ``legacy.dll`` (bundled binary), ``vendor.dll``
  (referenced, absent), an ``.ini`` file, a registry key, an environment
  variable and a hard-coded ``C:\\`` path;
* build scripts (``build.bat``, ``Makefile``, a GitHub Actions workflow);
* unresolved references: unit ``uMissingVendor`` and include ``gone.inc``.

The helper is data-only: no clocks, no randomness, no network.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["ENTERPRISE_APP", "write_enterprise_app", "EXPECTED"]

_DPR = """\
program ERPSystem;

uses
  Forms,
  MainForm in 'src\\MainForm.pas' {FormMain},
  uDataModule in 'src\\uDataModule.pas' {DM: TDataModule},
  uHttpClient in 'src\\uHttpClient.pas',
  uSoapClient in 'src\\uSoapClient.pas',
  uReports in 'src\\uReports.pas',
  uGrids in 'src\\uGrids.pas',
  uOffice in 'src\\uOffice.pas',
  uConfig in 'src\\uConfig.pas',
  uLegacy in 'src\\uLegacy.pas',
  uTransfer in 'src\\uTransfer.pas',
  uMissingVendor;

{$R *.res}

begin
  Application.Initialize;
  Application.CreateForm(TFormMain, FormMain);
  Application.Run;
end.
"""

_MAINFORM = """\
unit MainForm;

interface

uses
  Windows, Messages, SysUtils, Classes, Graphics, Controls, Forms, Dialogs,
  StdCtrls, uDataModule;

type
  TFormMain = class(TForm)
    ButtonLoad: TButton;
    procedure ButtonLoadClick(Sender: TObject);
  end;

var
  FormMain: TFormMain;

implementation

{$R *.dfm}

procedure TFormMain.ButtonLoadClick(Sender: TObject);
begin
  DM.Load;
end;

end.
"""

_DFM = """\
object FormMain: TFormMain
  Left = 0
  Top = 0
  Caption = 'ERP System'
  object ButtonLoad: TButton
    Left = 8
    Top = 8
    Caption = 'Load'
    OnClick = ButtonLoadClick
  end
end
"""

_DATAMODULE = """\
unit uDataModule;

interface

uses
  System.SysUtils, System.Classes, FireDAC.Comp.Client, FireDAC.Phys.Ora,
  Data.DB;

type
  TDM = class(TDataModule)
    Conn: TFDConnection;
    Query: TFDQuery;
    procedure Load;
  end;

var
  DM: TDM;

implementation

{$R *.dfm}

procedure TDM.Load;
begin
  Conn.Params.Clear;
  Conn.ConnectionString :=
    'DriverID=Ora;Database=ERPPROD;User_Name=erp_app;Password=S3cr3t!Pass';
  Conn.Connected := True;
  Query.SQL.Text := 'SELECT * FROM ORDERS WHERE ROWNUM < 10';
  Query.Open;
end;

end.
"""

_HTTP = """\
unit uHttpClient;

interface

uses
  SysUtils, Classes, IdHTTP, IdSSLOpenSSL;

function FetchOrders: string;

implementation

function FetchOrders: string;
var
  Http: TIdHTTP;
begin
  Http := TIdHTTP.Create(nil);
  try
    Result := Http.Get('https://api.example.com/v1/orders');
  finally
    Http.Free;
  end;
end;

end.
"""

_SOAP = """\
unit uSoapClient;

interface

uses
  SysUtils, InvokeRegistry, SOAPHTTPClient, Rio;

function CallBilling: string;

implementation

function CallBilling: string;
var
  Rio: THTTPRIO;
begin
  Rio := THTTPRIO.Create(nil);
  Rio.URL := 'http://billing.corp.example.com:8080/BillingService.asmx';
  Result := '';
end;

end.
"""

_REPORTS = """\
unit uReports;

interface

uses
  SysUtils, Classes, frxClass, frxDBSet;

procedure RunReport(const Name: string);

implementation

procedure RunReport(const Name: string);
var
  Report: TfrxReport;
begin
  Report := TfrxReport.Create(nil);
  Report.LoadFromFile('reports\\' + Name + '.fr3');
end;

end.
"""

_GRIDS = """\
unit uGrids;

interface

uses
  SysUtils, Classes, cxGrid, cxGridDBTableView, dxBarManager, JvEdit;

implementation

end.
"""

_OFFICE = """\
unit uOffice;

interface

uses
  SysUtils, ComObj, ActiveX, Variants;

procedure ExportToExcel;

implementation

procedure ExportToExcel;
var
  Excel: Variant;
begin
  Excel := CreateOleObject('Excel.Application');
  Excel.Visible := False;
end;

end.
"""

_CONFIG = """\
unit uConfig;

interface

uses
  SysUtils, IniFiles, Registry, Windows;

function ReadSettings: string;

implementation

function ReadSettings: string;
var
  Ini: TIniFile;
  Reg: TRegistry;
begin
  Ini := TIniFile.Create('erp.ini');
  Reg := TRegistry.Create;
  Reg.OpenKey('\\Software\\Contoso\\ERP', False);
  Result := GetEnvironmentVariable('ERP_HOME') + 'C:\\ERP\\data\\import';
  Ini.Free;
  Reg.Free;
end;

end.
"""

_LEGACY = """\
{$I common.inc}
{$I gone.inc}
unit uLegacy;

interface

function LegacyCalc(A, B: Integer): Integer; stdcall;
function VendorSign(const S: PChar): Integer; stdcall;

implementation

function LegacyCalc; external 'legacy.dll' name 'Calc';
function VendorSign; external 'vendor.dll';

end.
"""

_TRANSFER = """\
unit uTransfer;

interface

uses
  SysUtils, IdFTP, IdSMTP, IdMessage, SvcMgr, ExtCtrls;

type
  TTransferService = class(TService)
  end;

procedure SendNightlyExport;

implementation

procedure SendNightlyExport;
var
  Ftp: TIdFTP;
  Smtp: TIdSMTP;
begin
  Ftp := TIdFTP.Create(nil);
  Ftp.Host := 'ftp.partner.example.org';
  Smtp := TIdSMTP.Create(nil);
  Smtp.Host := 'smtp.corp.example.com';
end;

end.
"""

_COMMON_INC = """\
{$IFDEF MSWINDOWS}
  {$DEFINE ERP_WINDOWS}
{$ENDIF}
{$R+}
"""

_DPK = """\
package ErpCore;

{$R *.res}
{$DESCRIPTION 'ERP core components'}
{$DESIGNONLY}

requires
  rtl,
  vcl,
  dbrtl,
  vendorui;

contains
  CoreUtils in 'core\\CoreUtils.pas';

end.
"""

_COREUTILS = """\
unit CoreUtils;

interface

uses
  SysUtils, Classes;

function Trim2(const S: string): string;

implementation

function Trim2(const S: string): string;
begin
  Result := Trim(S);
end;

end.
"""

_JEDI = """\
unit JvEdit;

interface

uses
  SysUtils, Classes, StdCtrls;

type
  TJvEdit = class(TEdit)
  end;

implementation

end.
"""

_DPROJ = """\
<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <ProjectGuid>{11111111-2222-3333-4444-555555555555}</ProjectGuid>
    <MainSource>ERPSystem.dpr</MainSource>
    <ProjectVersion>19.2</ProjectVersion>
    <FrameworkType>VCL</FrameworkType>
    <Base>True</Base>
    <Config Condition="'$(Config)'==''">Release</Config>
    <Platform Condition="'$(Platform)'==''">Win32</Platform>
    <AppType>Application</AppType>
  </PropertyGroup>
  <PropertyGroup Condition="'$(Base)'!=''">
    <DCC_UnitSearchPath>lib\\jedi;core;$(DCC_UnitSearchPath)</DCC_UnitSearchPath>
    <DCC_Define>ERP_BUILD;$(DCC_Define)</DCC_Define>
    <DCC_Namespace>System;Xml;Data;Winapi;$(DCC_Namespace)</DCC_Namespace>
  </PropertyGroup>
  <ItemGroup>
    <DelphiCompile Include="$(MainSource)"><MainSource>MainSource</MainSource></DelphiCompile>
    <DCCReference Include="src\\MainForm.pas"><Form>FormMain</Form></DCCReference>
  </ItemGroup>
</Project>
"""

_DCC_CFG = """\
-$O+
-$W+
-U"lib\\jedi;core"
-I"src"
-R"resources"
-DERP_BUILD;RELEASE
-E"bin"
-N0"dcu"
"""

_ERP_INI = """\
[Database]
Server=ERPPROD
Port=1521

[Paths]
Import=C:\\ERP\\data\\import
"""

_SQL = """\
-- Oracle schema
CREATE SEQUENCE ORDERS_SEQ START WITH 1;
CREATE TABLE ORDERS (
  ID NUMBER(10) PRIMARY KEY,
  CREATED DATE DEFAULT SYSDATE,
  TOTAL NUMBER(12,2)
);
SELECT NVL(TOTAL, 0) FROM ORDERS, DUAL;
"""

_BUILD_BAT = """\
@echo off
call "%BDS%\\bin\\rsvars.bat"
msbuild ERPSystem.dproj /t:Build /p:Config=Release
dcc32 -B ERPSystem.dpr
"""

_MAKEFILE = """\
all:
\tlazbuild ERPSystem.lpi
\tmake -C core
"""

_WORKFLOW = """\
name: build
on: [push]
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - run: msbuild ERPSystem.dproj /t:Build
"""

_README = """\
# ERP System

Legacy order management. Build with build.bat. Requires Oracle client.
"""

#: Binary content: not valid text, begins with the PE magic.
_LEGACY_DLL = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + bytes(range(64))
_RES = b"\x00\x00\x00\x00\x20\x00\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00" + bytes(32)

ENTERPRISE_APP: dict[str, str | bytes] = {
    "ERPSystem.dpr": _DPR,
    "ERPSystem.dproj": _DPROJ,
    "ERPSystem.res": _RES,
    "dcc32.cfg": _DCC_CFG,
    "common.inc": _COMMON_INC,
    "src/MainForm.pas": _MAINFORM,
    "src/MainForm.dfm": _DFM,
    "src/uDataModule.pas": _DATAMODULE,
    "src/uHttpClient.pas": _HTTP,
    "src/uSoapClient.pas": _SOAP,
    "src/uReports.pas": _REPORTS,
    "src/uGrids.pas": _GRIDS,
    "src/uOffice.pas": _OFFICE,
    "src/uConfig.pas": _CONFIG,
    "src/uLegacy.pas": _LEGACY,
    "src/uTransfer.pas": _TRANSFER,
    "core/CoreUtils.pas": _COREUTILS,
    "packages/ErpCore.dpk": _DPK,
    "lib/jedi/JvEdit.pas": _JEDI,
    "lib/legacy.dll": _LEGACY_DLL,
    "config/erp.ini": _ERP_INI,
    "sql/schema_oracle.sql": _SQL,
    "build.bat": _BUILD_BAT,
    "Makefile": _MAKEFILE,
    ".github/workflows/build.yml": _WORKFLOW,
    "docs/README.md": _README,
    "reports/.keep": "",
    "empty_dir_marker/.gitkeep": "",
}

#: Facts about the tree that the Stage 1 tests assert.  They are stated here,
#: once, so a fixture edit and its expectations cannot drift apart silently.
EXPECTED = {
    "file_count": len(ENTERPRISE_APP),
    "pascal_units": 12,  # *.pas under src/, core/, lib/jedi (12 files)
    "projects": ["ERPSystem.dpr", "packages/ErpCore.dpk"],
    "secret_in_source": "S3cr3t!Pass",
    "unresolved_unit": "umissingvendor",
    "unresolved_include": "gone.inc",
    "bundled_dll": "lib/legacy.dll",
    "absent_dll": "vendor.dll",
    "absent_libraries": ["FastReport", "DevExpress"],
    "bundled_library": "JEDI",
}


def write_enterprise_app(root: Path) -> Path:
    """Materialise :data:`ENTERPRISE_APP` under *root* and return it."""

    root.mkdir(parents=True, exist_ok=True)
    for relative, content in ENTERPRISE_APP.items():
        target = root / Path(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        target.write_bytes(data)
    return root
