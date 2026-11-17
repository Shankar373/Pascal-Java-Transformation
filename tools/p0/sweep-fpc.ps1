<#
  P0 sweep: compile every Pascal fixture in corpus/ with host Free Pascal.

  Output (stdout, one line per fixture):
    PASS|<mode>|<relpath>
    FAIL|<mode>|<relpath>|<first error line>

  Mode is read from the fixture's own {$mode xxx} directive (first 8 lines);
  fixtures without one are compiled in the FPC default mode (-Mfpc), which is
  what `fpc file.pas` does with no flags.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-fpc.ps1 `
      [-FpcPath <fpc.exe>] [-Corpus <dir>] [-KeepTemp] [-Baseline <file>]

  -Baseline <file> archives this run's report verbatim (UTF-8, no BOM) so a
  pre-change run can be retained and compared later.  It is refused if the
  file already exists: an archive that silently overwrites itself preserves
  nothing.
#>
[CmdletBinding()]
param(
  [string]$FpcPath = 'C:\FPC\3.2.2\bin\i386-Win32\fpc.exe',
  [string]$Corpus,                 # default: <repo>/corpus, resolved below
  [string]$Baseline,               # archive this run's report here
  [switch]$KeepTemp
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus) { $Corpus = Join-Path $PSScriptRoot '..\..\corpus' }
$Corpus = (Resolve-Path -LiteralPath $Corpus).Path

if (-not (Test-Path -LiteralPath $FpcPath)) {
  throw "fpc not found at '$FpcPath'. Install FPC 3.2.2 or pass -FpcPath."
}

# --- archive mode (A4) ------------------------------------------------------
# Every report line is captured here as well as written to stdout, so the
# archived file is byte-identical to what a plain run would have printed.
$report = New-Object System.Collections.Generic.List[string]

function Emit([string]$Text) {
  $report.Add($Text)
  Write-Output $Text
}

if ($Baseline) {
  if (Test-Path -LiteralPath $Baseline) {
    throw "baseline '$Baseline' already exists; refusing to overwrite an archive"
  }
  $baselineDir = Split-Path -Parent -Path $Baseline
  if ($baselineDir -and -not (Test-Path -LiteralPath $baselineDir)) {
    New-Item -ItemType Directory -Path $baselineDir | Out-Null
  }
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
    Emit "FAIL|$mode|$rel|$err"
  } else {
    Emit "PASS|$mode|$rel"
  }

  if (-not $KeepTemp) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
}

if ($Baseline) {
  # UTF-8 without a BOM: the evidence files are read by diff and by bash.
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllLines($Baseline, $report, $utf8NoBom)
}
