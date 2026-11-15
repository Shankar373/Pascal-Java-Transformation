<#
  P0 parser recovery + span probe.

  The implementation prompt requires P0 to measure "parsing, recovery, spans".
  The golden corpus contains only valid Pascal (it is a *correctness* corpus and
  must stay that way), so recovery and span behavior are measured here on three
  small, deliberately malformed inputs generated at run time. This keeps the
  corpus untouched while still producing reproducible recovery evidence.

  Inputs
    rec_two_errors.pas  - TWO separate syntax errors (stray ')' statements)
                          followed by a trailing writeln. Decisive test:
                            - a parser that stops at the first error reports 1
                            - a recovering parser reports 2 AND still parses
                              the trailing statement
    rec_missing_end.pas - body with no terminating "end." (EOF recovery)
    rec_valid_control.pas - fully valid; both parsers must report OK, which
                          proves the harness itself is not the thing failing

  Recorded per input, per parser:
    - number of errors reported (first-error-only vs multi-error recovery)
    - whether any tree/output was produced after the error (recovery)
    - the reported source position (span evidence)

  Output (stdout):
    INPUT|<name>|<description>
    TS |<name>|errors=<n>|missing=<n>|nodes_after_error=<yes/no>|first=<span text>
    DA |<name>|<OK|ERROR>|<position or node count>|<message>
    VERDICT|<name>|<finding>

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools/p0/probe-recovery.ps1 `
        -TreeSitterExe <tree-sitter.exe> -GrammarDir <grammar clone> `
        -MingwBin <mingw64\bin> -DelphiASTHarness <delphiast_eval.exe>
#>
[CmdletBinding()]
param(
  [string]$TreeSitterExe,
  [Parameter(Mandatory = $true)][string]$GrammarDir,
  [Parameter(Mandatory = $true)][string]$MingwBin,
  [Parameter(Mandatory = $true)][string]$DelphiASTHarness
)

$ErrorActionPreference = 'Stop'
if (-not $TreeSitterExe) {
  $TreeSitterExe = Join-Path $env:USERPROFILE 'node_modules\tree-sitter-cli\tree-sitter.exe'
}
$GrammarDir       = (Resolve-Path -LiteralPath $GrammarDir).Path
$MingwBin         = (Resolve-Path -LiteralPath $MingwBin).Path
$DelphiASTHarness = (Resolve-Path -LiteralPath $DelphiASTHarness).Path
foreach ($need in $TreeSitterExe, $DelphiASTHarness) {
  if (-not (Test-Path -LiteralPath $need)) { throw "required tool not found at '$need'." }
}

$work = Join-Path ([System.IO.Path]::GetTempPath()) ('p0-recovery-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null

# --- inputs -----------------------------------------------------------------

$inputs = [ordered]@{
  'rec_two_errors.pas' = @'
program TwoErrors;
begin
  ) ;
  ) ;
  writeln('tail-visible');
end.
'@
  'rec_missing_end.pas' = @'
program MissingEnd;
begin
  writeln('body-ran');
'@
  'rec_valid_control.pas' = @'
program ValidControl;
var
  X: Integer;
begin
  X := 41;
  writeln('control=', X + 1);
end.
'@
}

$desc = @{
  'rec_two_errors.pas'   = 'two syntax errors + trailing statement (does it report both? does it reach the tail?)'
  'rec_missing_end.pas'  = 'missing end. at EOF (EOF recovery)'
  'rec_valid_control.pas'= 'valid control - both parsers must accept'
}

foreach ($n in $inputs.Keys) {
  Set-Content -Path (Join-Path $work $n) -Value $inputs[$n] -Encoding ASCII
}

$prevPath = $env:PATH; $prevCC = $env:CC
$env:CC = 'gcc'
$env:PATH = $MingwBin + ';' + $env:PATH

try {
  foreach ($n in $inputs.Keys) {
    $file = Join-Path $work $n
    Write-Output "INPUT|$n|$($desc[$n])"

    # --- tree-sitter: default output carries ranges, so spans are observable ---
    # tree-sitter prints a benign "not configured any parser directories" notice
    # on stderr; with 2>&1 PowerShell 5.1 turns that into an ErrorRecord, which
    # $ErrorActionPreference='Stop' would promote to terminating. Scope the
    # preference down for the native call only - the parser's real verdict is
    # taken from stdout below, never from stream state.
    Push-Location $GrammarDir
    try {
      $ErrorActionPreference = 'Continue'
      $tsOut = @(& $TreeSitterExe parse $file 2>&1 | ForEach-Object { "$_" })
    } finally { Pop-Location; $ErrorActionPreference = 'Stop' }

    $tsText  = $tsOut -join "`n"
    $errN    = ([regex]::Matches($tsText, '\(ERROR')).Count
    $missN   = ([regex]::Matches($tsText, '\(MISSING')).Count
    $nodeN   = ([regex]::Matches($tsText, '\(')).Count
    # Is there real content parsed after the error position? Count nodes on
    # lines that follow the first ERROR/MISSING line.
    $after   = $false
    $seenErr = $false
    foreach ($l in $tsOut) {
      if ($l -match '\((ERROR|MISSING)') { $seenErr = $true; continue }
      if ($seenErr -and $l -match '^\s*\(') { $after = $true; break }
    }
    $firstErrLine = ($tsOut | Where-Object { $_ -match '\((ERROR|MISSING)' } | Select-Object -First 1)
    if ($firstErrLine) { $firstErrLine = $firstErrLine.Trim() }
    if ($firstErrLine -and $firstErrLine.Length -gt 150) { $firstErrLine = $firstErrLine.Substring(0,150) + ' ...' }

    Write-Output ('TS |{0}|errors={1}|missing={2}|nodes={3}|nodes_after_error={4}|first={5}' -f `
      $n, $errN, $missN, $nodeN, $(if ($after) { 'yes' } else { 'no' }), $firstErrLine)

    # --- DelphiAST: one RESULT line, first error position --------------------
    $ErrorActionPreference = 'Continue'
    $daOut = @(& $DelphiASTHarness $file 2>&1 | ForEach-Object { "$_" })
    $ErrorActionPreference = 'Stop'
    $res   = $daOut | Where-Object { $_ -match '^RESULT\|' } | Select-Object -First 1
    if (-not $res) { $res = 'RESULT|<none>|HARNESS-NO-OUTPUT' }

    # The harness emits one RESULT per file; also count how many RESULT lines
    # it produced, to show whether it reports further errors past the first.
    $resCount = ($daOut | Where-Object { $_ -match '^RESULT\|' }).Count

    if ($res -match '^RESULT\|(.+)\|OK\|(\d+)$') {
      Write-Output ('DA |{0}|OK|nodes={1}|result_lines={2}' -f $n, $Matches[2], $resCount)
    } elseif ($res -match '^RESULT\|(.+)\|ERROR\|([^|]+)\|(.*)$') {
      Write-Output ('DA |{0}|ERROR|position={1}|message={2}|result_lines={3}' -f `
        $n, $Matches[2], $Matches[3], $resCount)
    } else {
      Write-Output ('DA |{0}|{1}' -f $n, $res)
    }

    # --- verdict -------------------------------------------------------------
    if ($n -eq 'rec_valid_control.pas') {
      $ok = ($errN -eq 0 -and $missN -eq 0 -and $res -match '\|OK\|')
      $ctl = if ($ok) { 'PASS' } else { 'FAIL' }
      $daState = if ($res -match '\|OK\|') { 'OK' } else { 'ERROR' }
      Write-Output ("VERDICT|{0}|control={1} accepted by both parsers (tree-sitter errors={2}; DelphiAST={3})" -f `
        $n, $ctl, $errN, $daState)
    } elseif ($n -eq 'rec_two_errors.pas') {
      $tsMulti = $errN -ge 2
      $tsTail  = $after
      $daMulti = $resCount -ge 2
      Write-Output ("VERDICT|{0}|tree-sitter reported {1} error node(s) {2} continuing past them; DelphiAST produced {3} result line(s) {4}" -f `
        $n, $errN, $(if ($tsTail) { 'and' } else { 'WITHOUT' }), $resCount,
        $(if ($daMulti) { 'and reported more than one' } else { '(first error only)' }))
    } else {
      Write-Output ("VERDICT|{0}|tree-sitter errors={1} missing={2}; DelphiAST={3}" -f `
        $n, $errN, $missN, $(if ($res -match '\|OK\|') { 'OK' } else { 'ERROR' }))
    }
    Write-Output ''
  }
} finally {
  $env:PATH = $prevPath
  $env:CC   = $prevCC
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
