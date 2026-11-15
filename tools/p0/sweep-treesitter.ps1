<#
  P0 sweep: parse every Pascal fixture in corpus/ with tree-sitter-pascal.

  Requires:
    - tree-sitter CLI on PATH (evaluated with 0.24.5)
    - a clone of https://github.com/Isopod/tree-sitter-pascal at v0.10.2 (042119e)
      passed via -GrammarDir; the CLI is run from that directory so it picks up
      the grammar, and CC=gcc plus a MinGW bin dir on PATH so it does not default
      to cl.exe (absent on this host).
    - grammar built once via `tree-sitter generate` (src/parser.c present).

  Output (stdout, one line per fixture):
    PASS|<relpath>
    FAIL|<relpath>|errors=<n>,missing=<n>

  "errors" counts (ERROR nodes and "missing" counts MISSING nodes in the parse
  output; either > 0 means the grammar did not accept the file cleanly.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-treesitter.ps1 -GrammarDir <clone> -MingwBin <dir> [-Corpus <dir>]
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$GrammarDir,
  [Parameter(Mandatory = $true)][string]$MingwBin,
  [string]$TreeSitterCmd = 'C:\Users\bandi\node_modules\.bin\tree-sitter.cmd',
  [string]$Corpus                 # default: <repo>/corpus, resolved below
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus) { $Corpus = Join-Path $PSScriptRoot '..\..\corpus' }
$Corpus     = (Resolve-Path -LiteralPath $Corpus).Path
$GrammarDir = (Resolve-Path -LiteralPath $GrammarDir).Path
$MingwBin   = (Resolve-Path -LiteralPath $MingwBin).Path

if (-not (Test-Path -LiteralPath $TreeSitterCmd)) { throw "tree-sitter CLI not found at '$TreeSitterCmd'." }
if (-not (Test-Path -LiteralPath (Join-Path $GrammarDir 'src\parser.c'))) {
  throw "grammar not generated in '$GrammarDir' (src/parser.c missing). Run `tree-sitter generate` there first."
}

# tree-sitter defaults to cl.exe when CC is unset; this host builds with gcc.
$env:CC = 'gcc'
$env:PATH = "$MingwBin;$env:PATH"

$fixtures = Get-ChildItem -LiteralPath $Corpus -Recurse -File |
  Where-Object { $_.Extension -in '.pas', '.dpr', '.lpr' } |
  Sort-Object FullName

Push-Location $GrammarDir
try {
  foreach ($f in $fixtures) {
    $rel = $f.FullName.Substring($Corpus.Length + 1)

    # tree-sitter prints a benign "not configured any parser directories"
    # warning on stderr. Under EAP=Stop, PS 5.1 turns native stderr into a
    # terminating ErrorRecord and aborts the sweep, so send stderr to a file
    # instead of the pipeline and suspend Stop for the duration of the call.
    $errFile = Join-Path ([System.IO.Path]::GetTempPath()) `
      ('ts-err-' + [guid]::NewGuid().ToString('N') + '.txt')
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = (& $TreeSitterCmd parse $f.FullName 2>$errFile |
      ForEach-Object { "$_" }) -join "`n"
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    Remove-Item $errFile -Force -ErrorAction SilentlyContinue

    if ([string]::IsNullOrWhiteSpace($out)) {
      # No parse text at all means the tool failed, not that the file is clean.
      Write-Output "FAIL|$rel|tool-failure|exit=$exitCode"
      continue
    }

    $errors  = ([regex]::Matches($out, '\(ERROR')).Count
    $missing = ([regex]::Matches($out, '\(MISSING')).Count

    if ($errors -eq 0 -and $missing -eq 0) {
      Write-Output "PASS|$rel"
    } else {
      Write-Output "FAIL|$rel|errors=$errors,missing=$missing"
    }
  }
}
finally {
  Pop-Location
}
