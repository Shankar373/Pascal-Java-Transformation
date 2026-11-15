<#
  P0 sweep: compile every Pascal fixture in corpus/ with host Free Pascal.

  Output (stdout, one line per fixture):
    PASS|<mode>|<relpath>
    FAIL|<mode>|<relpath>|<first error line>

  Mode is read from the fixture's own {$mode xxx} directive (first 8 lines);
  fixtures without one are compiled in the FPC default mode (-Mfpc), which is
  what `fpc file.pas` does with no flags.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-fpc.ps1 [-FpcPath <fpc.exe>] [-Corpus <dir>] [-KeepTemp]
#>
[CmdletBinding()]
param(
  [string]$FpcPath = 'C:\FPC\3.2.2\bin\i386-Win32\fpc.exe',
  [string]$Corpus,                 # default: <repo>/corpus, resolved below
  [switch]$KeepTemp
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus) { $Corpus = Join-Path $PSScriptRoot '..\..\corpus' }
$Corpus = (Resolve-Path -LiteralPath $Corpus).Path

if (-not (Test-Path -LiteralPath $FpcPath)) {
  throw "fpc not found at '$FpcPath'. Install FPC 3.2.2 or pass -FpcPath."
}

$fixtures = Get-ChildItem -LiteralPath $Corpus -Recurse -File |
  Where-Object { $_.Extension -in '.pas', '.dpr', '.lpr' } |
  Sort-Object FullName

$unitDirs = Get-ChildItem -LiteralPath $Corpus -Recurse -Directory | ForEach-Object { $_.FullName }

foreach ($f in $fixtures) {
  $rel = $f.FullName.Substring($Corpus.Length + 1)

  # Read the fixture header to pick up its declared language mode.
  $mode = 'fpc'
  $head = Get-Content -Path $f.FullName -TotalCount 8 -ErrorAction SilentlyContinue
  foreach ($line in $head) {
    if ($line -match '\{\$mode\s+(\w+)') { $mode = $Matches[1]; break }
  }

  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('p0-fpc-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmp | Out-Null

  $fpcArgs = @("-M$mode", "-FE$tmp", "-FU$tmp", '-vew')
  foreach ($d in $unitDirs) { $fpcArgs += "-Fu$d"; $fpcArgs += "-Fi$d" }
  $fpcArgs += $f.FullName

  $out = & $FpcPath @fpcArgs 2>&1 | ForEach-Object { "$_" }
  $err = $out | Where-Object { $_ -match '^\s*\S+\((\d+),(\d+)\)\s+(Error|Fatal)' } | Select-Object -First 1

  if ($err) {
    Write-Output "FAIL|$mode|$rel|$err"
  } else {
    Write-Output "PASS|$mode|$rel"
  }

  if (-not $KeepTemp) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
}
