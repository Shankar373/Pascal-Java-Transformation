<#
  P0 dialect probes: answer one Free Pascal dialect question per probe by
  compiling a minimal program with host FPC 3.2.2 and recording the observable
  result. These probes are the evidence behind DIALECT_COMPILER_MATRIX.md.

  Output (stdout), one line per probe:
    <id>|<question>|expect=<PASS|FAIL>|got=<PASS|FAIL>|<OK|UNEXPECTED>|<detail>
  followed by a ppu scan reporting where AssignFile/CloseFile are declared.

  Every probe writes its source into a temp directory (removed on exit unless
  -KeepTemp) so that no stale .ppu/.o from a previous run can contaminate it.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools/p0/probes.ps1 [-KeepTemp]
#>
[CmdletBinding()]
param(
  [string]$FpcPath = 'C:\FPC\3.2.2\bin\i386-Win32\fpc.exe',
  [switch]$KeepTemp
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $FpcPath)) { throw "fpc not found at '$FpcPath'. Install FPC 3.2.2 or pass -FpcPath." }

$root = Join-Path ([System.IO.Path]::GetTempPath()) ('p0-probes-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null

$ver = (& $FpcPath -iV 2>&1 | Select-Object -First 1)
Write-Output "HOST|$FpcPath|version=$ver"

function Invoke-Probe {
  param(
    [Parameter(Mandatory = $true)][string]$Id,
    [Parameter(Mandatory = $true)][string]$Question,
    [Parameter(Mandatory = $true)][string]$FileName,
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Mode,
    [string[]]$Extra = @(),
    [string]$Expect = 'PASS'
  )

  $dir = Join-Path $root $Id
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $path = Join-Path $dir $FileName
  Set-Content -Path $path -Value $Source -Encoding ASCII

  $fpcArgs = @("-M$Mode", "-FE$dir", "-FU$dir", "-vew") + $Extra + @($path)
  $lines = @(& $FpcPath @fpcArgs 2>&1 | ForEach-Object { "$_" })

  $errLine  = $lines | Where-Object { $_ -match '\(\d+,\d+\)\s+(Error|Fatal)' } | Select-Object -First 1
  $okLine   = $lines | Where-Object { $_ -match 'lines compiled' } | Select-Object -First 1
  $warnLine = $lines | Where-Object { $_ -match 'Warning' } | Select-Object -First 1

  if (-not $errLine -and -not $okLine) {
    # FPC sometimes reports a bare "Error:/Fatal:" with no line/col.
    $bare = $lines | Where-Object { $_ -match '\b(Error|Fatal):' } | Select-Object -First 1
    if ($bare) { $errLine = $bare }
  }

  if ($errLine) {
    $got = 'FAIL'; $detail = $errLine.Trim()
  } elseif ($okLine) {
    $got = 'PASS'; $detail = $okLine.Trim()
    if ($warnLine) { $detail = $detail + ' ; ' + $warnLine.Trim() }
  } else {
    $got = 'UNKNOWN'; $detail = ($lines -join ' // ')
  }

  $flag = 'UNEXPECTED'
  if ($got -eq $Expect) { $flag = 'OK' }

  Write-Output ('{0}|{1}|expect={2}|got={3}|{4}|{5}' -f $Id, $Question, $Expect, $got, $flag, $detail)
}

# --- Result identifier availability per dialect mode ------------------------

$srcResult = @'
program ProbeResult;
function F: Integer;
begin
  Result := 1;
end;
begin
  WriteLn(F);
end.
'@

$srcNameAssign = @'
program ProbeName;
function F: Integer;
begin
  F := 1;
end;
begin
  WriteLn(F);
end.
'@

Invoke-Probe -Id 'P01' -Question 'Result identifier visible in -Mfpc?' `
  -FileName 'probe_result.pas' -Source $srcResult -Mode 'fpc' -Expect 'FAIL'
Invoke-Probe -Id 'P02' -Question 'Result identifier visible in -Mtp?' `
  -FileName 'probe_result.pas' -Source $srcResult -Mode 'tp' -Expect 'FAIL'
Invoke-Probe -Id 'P03' -Question 'Result identifier visible in -Mobjfpc?' `
  -FileName 'probe_result.pas' -Source $srcResult -Mode 'objfpc' -Expect 'PASS'
Invoke-Probe -Id 'P04' -Question 'Result identifier visible in -Mdelphi?' `
  -FileName 'probe_result.pas' -Source $srcResult -Mode 'delphi' -Expect 'PASS'
Invoke-Probe -Id 'P05' -Question 'function-name assignment works in -Mfpc (control for P01)?' `
  -FileName 'probe_name.pas' -Source $srcNameAssign -Mode 'fpc' -Expect 'PASS'

# --- AssignFile/CloseFile: declared in ObjPas, not System -------------------

$srcAssign = @'
program ProbeAssign;
var
  F: TextFile;
begin
  AssignFile(F, 'x.txt');
  Rewrite(F);
  CloseFile(F);
end.
'@

$srcAssignObjPas = @'
program ProbeAssignObjPas;
uses
  ObjPas;
var
  F: TextFile;
begin
  AssignFile(F, 'x.txt');
  Rewrite(F);
  CloseFile(F);
end.
'@

$srcSystemAssign = @'
program ProbeSystemAssign;
var
  F: TextFile;
begin
  System.AssignFile(F, 'x.txt');
end.
'@

$srcObjPasAssign = @'
program ProbeObjPasAssign;
var
  F: TextFile;
begin
  ObjPas.AssignFile(F, 'x.txt');
end.
'@

Invoke-Probe -Id 'P06' -Question 'bare AssignFile/CloseFile visible in -Mfpc?' `
  -FileName 'probe_assign.pas' -Source $srcAssign -Mode 'fpc' -Expect 'FAIL'
Invoke-Probe -Id 'P07' -Question 'bare AssignFile/CloseFile visible in -Mobjfpc?' `
  -FileName 'probe_assign.pas' -Source $srcAssign -Mode 'objfpc' -Expect 'PASS'
Invoke-Probe -Id 'P08' -Question 'bare AssignFile/CloseFile visible in -Mdelphi?' `
  -FileName 'probe_assign.pas' -Source $srcAssign -Mode 'delphi' -Expect 'PASS'
Invoke-Probe -Id 'P09' -Question 'uses ObjPas restores AssignFile in -Mfpc?' `
  -FileName 'probe_assign_objpas.pas' -Source $srcAssignObjPas -Mode 'fpc' -Expect 'PASS'
Invoke-Probe -Id 'P10' -Question 'System.AssignFile resolves in -Mfpc (System lacks it)?' `
  -FileName 'probe_sysassign.pas' -Source $srcSystemAssign -Mode 'fpc' -Expect 'FAIL'
Invoke-Probe -Id 'P11' -Question 'ObjPas.AssignFile resolves in -Mobjfpc without a uses clause?' `
  -FileName 'probe_objpasassign.pas' -Source $srcObjPasAssign -Mode 'objfpc' -Expect 'PASS'

# --- Unit name must equal file name; program name need not ------------------

$srcUnitMatch = @'
unit ProbeUnit;
interface
implementation
end.
'@

$srcUnitMismatch = @'
unit OtherName;
interface
implementation
end.
'@

$srcProgMismatch = @'
program WrongName;
begin
  WriteLn('ok');
end.
'@

Invoke-Probe -Id 'P12' -Question 'unit name equal to file name compiles (-Mdelphi)?' `
  -FileName 'ProbeUnit.pas' -Source $srcUnitMatch -Mode 'delphi' -Expect 'PASS'
Invoke-Probe -Id 'P13' -Question 'unit name different from file name is rejected?' `
  -FileName 'ProbeUnit.pas' -Source $srcUnitMismatch -Mode 'delphi' -Expect 'FAIL'
Invoke-Probe -Id 'P14' -Question 'program name different from file name is accepted?' `
  -FileName 'probe_prog.pas' -Source $srcProgMismatch -Mode 'fpc' -Expect 'PASS'

# --- Length-suffixed short string in a variant record -----------------------

$srcVariant = @'
program ProbeVariant;
type
  TTagged = record
    Kind: (kInt, kStr);
    case Integer of
      0: (IntValue: LongInt);
      1: (StrValue: string[31]);
  end;
var
  V: TTagged;
begin
  V.Kind := kStr;
  V.StrValue := 'abc';
  WriteLn(V.StrValue);
end.
'@

Invoke-Probe -Id 'P15' -Question 'string[31] variant-record field compiles in -Mfpc?' `
  -FileName 'probe_variant.pas' -Source $srcVariant -Mode 'fpc' -Expect 'PASS'

# --- Nested {$...} inside a {...} comment -----------------------------------

$srcComment = @'
program ProbeComment;
{ outer {$mode objfpc} inner }
begin
  WriteLn('ok');
end.
'@

Invoke-Probe -Id 'P16' -Question 'directive nested inside a brace comment in -Mfpc?' `
  -FileName 'probe_comment.pas' -Source $srcComment -Mode 'fpc' -Expect 'PASS'
Invoke-Probe -Id 'P17' -Question 'directive nested inside a brace comment in -Mdelphi?' `
  -FileName 'probe_comment.pas' -Source $srcComment -Mode 'delphi' -Expect 'FAIL'

# --- Non-standard mode flag accepted by the compiler ------------------------

$srcIso = @'
program ProbeIso;
begin
  WriteLn('ok');
end.
'@

Invoke-Probe -Id 'P18' -Question 'does fpc 3.2.2 accept -Miso (absent from -h list)?' `
  -FileName 'probe_iso.pas' -Source $srcIso -Mode 'iso' -Expect 'PASS'

# --- Where are AssignFile/CloseFile actually declared? ----------------------

Write-Output '--- ppu scan: which RTL unit declares AssignFile/CloseFile ---'
# $FpcPath = C:\FPC\3.2.2\bin\i386-Win32\fpc.exe -> three Split-Path hops:
# ...i386-Win32 -> ...bin -> C:\FPC\3.2.2 (the install root holding units\).
$fpcRoot = Split-Path (Split-Path (Split-Path $FpcPath))
$unitRoot = Join-Path $fpcRoot 'units'
foreach ($unitFile in 'system.ppu', 'objpas.ppu') {
  $hit = Get-ChildItem -LiteralPath $unitRoot -Recurse -Filter $unitFile -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($hit) {
    $ascii = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($hit.FullName))
    Write-Output ('{0}|path={1}|AssignFile={2}|CloseFile={3}|Rewrite={4}|Reset={5}' -f `
      $unitFile, $hit.FullName, ($ascii -match 'AssignFile'), ($ascii -match 'CloseFile'), `
      ($ascii -match 'Rewrite'), ($ascii -match 'Reset'))
  } else {
    Write-Output ("{0}|NOT FOUND under {1}" -f $unitFile, $unitRoot)
  }
}

if (-not $KeepTemp) { Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
