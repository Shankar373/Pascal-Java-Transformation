<#
  P0 sweep: parse every Pascal fixture in corpus/ with DelphiAST under FPC.

  Requires:
    - DelphiAST clone (Isopod/DelphiAST @ 3840253, MPL-2.0) with the P0 patch
      from docs/p0/evidence/delphiast-fpc-helper-recursion.patch applied to
      Source/SimpleParser/SimpleParser.pas (without it the helper getter
      recurses and every input dies with EStackOverflow under FPC).
    - the evaluation harness built from delphiast_eval.dpr (see
      docs/p0/PARSER_EVALUATION.md for the build command).

  The harness emits one line per input:
    RESULT|<fullpath>|OK|<nodes>
    RESULT|<fullpath>|ERROR|<line>:<col>|<message>

  This script re-emits them one line per fixture, with the path made relative
  to the corpus, the status moved into field 2, and the RESULT wrapper dropped:
    <relpath>|PASS|nodes=<n>
    <relpath>|FAIL|<line>:<col>|<message>

  Fail-closed: a fixture for which the harness produced no RESULT line at all
  is reported as "<relpath>|FAIL|no result line from harness" - a missing
  verdict can never be mistaken for a pass.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-delphiast.ps1 `
        -Harness <delphiast_eval.exe> [-Corpus <dir>]
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Harness,
  [string]$Corpus                 # default: <repo>/corpus, resolved below
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus) { $Corpus = Join-Path $PSScriptRoot '..\..\corpus' }
$Corpus = (Resolve-Path -LiteralPath $Corpus).Path
$Harness = (Resolve-Path -LiteralPath $Harness).Path

if (-not (Test-Path -LiteralPath $Harness)) { throw "harness not found at '$Harness'." }

$fixtures = Get-ChildItem -LiteralPath $Corpus -Recurse -File |
  Where-Object { $_.Extension -in '.pas', '.dpr', '.lpr' } |
  Sort-Object FullName

# The harness takes files as arguments; feed it in one batch so the run is a
# single process (parse errors are data, not harness failures - exit code 0).
$paths = $fixtures | ForEach-Object { $_.FullName }
$lines = & $Harness @paths 2>&1 | ForEach-Object { "$_" }

$byFile = @{}
foreach ($l in $lines) {
  if ($l -match '^RESULT\|(.+)\|OK\|(\d+)$') {
    $byFile[$Matches[1]] = "PASS|nodes=$($Matches[2])"
  } elseif ($l -match '^RESULT\|(.+)\|ERROR\|([^|]+)\|(.*)$') {
    $byFile[$Matches[1]] = "FAIL|$($Matches[2])|$($Matches[3])"
  }
}

foreach ($f in $fixtures) {
  $rel = $f.FullName.Substring($Corpus.Length + 1)
  if ($byFile.ContainsKey($f.FullName)) {
    Write-Output "$rel|$($byFile[$f.FullName])"
  } else {
    Write-Output "$rel|FAIL|no result line from harness"
  }
}
