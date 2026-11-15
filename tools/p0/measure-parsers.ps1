<#
  P0 parser performance measurement: wall-clock time and peak memory for both
  parser candidates over the same golden corpus.

  The implementation prompt requires P0 to "measure parsing, recovery, spans,
  supported constructs, time and memory". Recovery and construct coverage are
  evidenced by the pass/fail sweeps (sweep-treesitter.ps1 / sweep-delphiast.ps1)
  and PARSER_EVALUATION.md; this script supplies the time and memory half.

  Two measurement shapes, both over the identical fixture set:

    BATCH   - one process parses all fixtures (steady-state throughput, the
              figure quoted for "can this tool process a corpus?")
    PERFILE - one process per fixture (per-file cost, including process
              start-up; needed because DelphiAST's documented usage is
              one unit at a time)

  Both parsers are launched as their real native executable rather than through
  an npm/cmd shim, so the sampled working set is the parser's, not a launcher's:
    tree-sitter : node_modules\tree-sitter-cli\tree-sitter.exe
    DelphiAST   : the delphiast_eval.exe harness (built from the P0 patch)

  Memory is sampled from the live process handle every 5 ms while it runs
  (peak working set). System.Diagnostics.Process caches field values, so each
  sample calls Refresh() first and reading stops as soon as the process exits.

  Output (stdout):
    META|parser|<name>|version=<v>|mode=<BATCH|PERFILE>
    BATCH|<parser>|files=<n>|elapsed_ms=<n>|peak_ws_mb=<n.n>|exit=<n>|out_lines=<n>
    PERFILE|<parser>|<relpath>|elapsed_ms=<n>|peak_ws_mb=<n.n>|out_lines=<n>
    SUMMARY|parser=<name>|files=<n>|total_ms=<n>|mean_ms=<n.n>|max_peak_ws_mb=<n.n>

  out_lines is a validity signal: a measurement whose parser produced no output
  would be measuring an aborted run, so non-zero out_lines is what makes each
  timing/memory figure meaningful. BATCH exit is the real process exit status
  (read through the raw .NET API, because Start-Process reports null).

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools/p0/measure-parsers.ps1 `
        -TreeSitterExe <path\to\tree-sitter.exe> -GrammarDir <grammar clone> `
        -MingwBin <mingw64\bin> -DelphiASTHarness <path\to\delphiast_eval.exe> `
        [-Corpus <dir>] [-SkipPerFile]
#>
[CmdletBinding()]
param(
  [string]$TreeSitterExe,
  [Parameter(Mandatory = $true)][string]$GrammarDir,
  [Parameter(Mandatory = $true)][string]$MingwBin,
  [Parameter(Mandatory = $true)][string]$DelphiASTHarness,
  [string]$Corpus,
  [switch]$SkipPerFile
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus)   { $Corpus   = Join-Path $PSScriptRoot '..\..\corpus' }
if (-not $TreeSitterExe) {
  $TreeSitterExe = Join-Path $env:LOCALAPPDATA 'npm\node_modules\tree-sitter-cli\tree-sitter.exe'
  if (-not (Test-Path -LiteralPath $TreeSitterExe)) {
    $TreeSitterExe = Join-Path $env:USERPROFILE 'node_modules\tree-sitter-cli\tree-sitter.exe'
  }
}

# Shared MSVC-convention argument quoter; must be loaded in the body (not in a
# param() default) because $PSScriptRoot is not populated there.
. (Join-Path $PSScriptRoot 'NativeArgument.ps1')
$Corpus           = (Resolve-Path -LiteralPath $Corpus).Path
$GrammarDir       = (Resolve-Path -LiteralPath $GrammarDir).Path
$MingwBin         = (Resolve-Path -LiteralPath $MingwBin).Path
$DelphiASTHarness = (Resolve-Path -LiteralPath $DelphiASTHarness).Path

foreach ($need in $TreeSitterExe, $DelphiASTHarness) {
  if (-not (Test-Path -LiteralPath $need)) { throw "required tool not found at '$need'." }
}

$fixtures = Get-ChildItem -LiteralPath $Corpus -Recurse -File |
  Where-Object { $_.Extension -in '.pas', '.dpr', '.lpr' } |
  Sort-Object FullName

# Launch a native process, sample its peak working set until it exits, and
# return @{ ElapsedMs; PeakWs; ExitCode; Stdout }.
function Invoke-Measured {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [string]$WorkingDirectory,
    [string[]]$ExtraPath
  )

  $prevPath = $env:PATH
  $prevCC   = $env:CC
  if ($ExtraPath) { $env:PATH = ($ExtraPath -join ';') + ';' + $env:PATH }
  if (-not $WorkingDirectory) { $WorkingDirectory = (Get-Location).Path }

  # Raw .NET Process API rather than Start-Process: the latter returns a Process
  # whose ExitCode stays null after exit, which would record a fake exit status.
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName               = $Exe
  # PS 5.1/.NET Framework has no ProcessStartInfo.ArgumentList, so the command
  # line is a single string. Hand-quoting it with '"' + $arg + '"' breaks on an
  # embedded quote or a trailing backslash; use the shared MSVC-convention
  # quoter instead (see NativeArgument.ps1).
  $psi.Arguments              = ConvertTo-NativeArgument -ArgumentList $Arguments
  $psi.WorkingDirectory       = $WorkingDirectory
  $psi.UseShellExecute        = $false
  $psi.CreateNoWindow         = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError  = $true

  $sw   = [System.Diagnostics.Stopwatch]::StartNew()
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
  $stderrTask = $proc.StandardError.ReadToEndAsync()

  $peak = 0L
  while (-not $proc.HasExited) {
    try {
      $proc.Refresh()
      if ($proc.WorkingSet64 -gt $peak) { $peak = $proc.WorkingSet64 }
    } catch { }   # process can exit between the check and the read
    Start-Sleep -Milliseconds 5
  }
  $proc.WaitForExit()
  $sw.Stop()

  try {
    $proc.Refresh()
    if ($proc.PeakWorkingSet64 -gt $peak) { $peak = $proc.PeakWorkingSet64 }
    $exitCode = $proc.ExitCode
  } catch { $exitCode = -1 }

  $stdout = @()
  try {
    $text = $stdoutTask.Result
    if ($text) { $stdout = @($text -split "\r?\n" | Where-Object { $_ -ne '' }) }
  } catch { $stdout = @() }

  $env:PATH = $prevPath
  $env:CC   = $prevCC

  [pscustomobject]@{
    ElapsedMs  = [int]$sw.ElapsedMilliseconds
    PeakWs     = [int64]$peak
    ExitCode   = $exitCode
    OutLines   = $stdout.Count
    HasOutput  = ($stdout.Count -gt 0)
    Stdout     = $stdout
  }
}

function Convert-Rel([string]$full) { $full.Substring($Corpus.Length + 1) }

# ---------------------------------------------------------------------------

$tsVersion = (& $TreeSitterExe --version 2>&1 | Select-Object -First 1)
Write-Output "META|parser|tree-sitter|version=$tsVersion|mode=BATCH"
Write-Output "META|parser|DelphiAST|version=commit-3840253+p0-patch|mode=BATCH"

# tree-sitter needs the grammar build dir as cwd plus gcc on PATH; the DelphiAST
# harness needs neither.
$tsPaths   = $fixtures | ForEach-Object { $_.FullName }
$tsArgs    = @('parse') + $tsPaths
$tsBatch   = Invoke-Measured -Exe $TreeSitterExe -Arguments $tsArgs `
                -WorkingDirectory $GrammarDir -ExtraPath @($MingwBin)
Write-Output ("BATCH|tree-sitter|files={0}|elapsed_ms={1}|peak_ws_mb={2}|exit={3}|out_lines={4}" -f `
  $fixtures.Count, $tsBatch.ElapsedMs, [math]::Round($tsBatch.PeakWs / 1MB, 2),
  $tsBatch.ExitCode, $tsBatch.OutLines)

$daBatch   = Invoke-Measured -Exe $DelphiASTHarness -Arguments $tsPaths
Write-Output ("BATCH|DelphiAST|files={0}|elapsed_ms={1}|peak_ws_mb={2}|exit={3}|out_lines={4}" -f `
  $fixtures.Count, $daBatch.ElapsedMs, [math]::Round($daBatch.PeakWs / 1MB, 2),
  $daBatch.ExitCode, $daBatch.OutLines)

if ($SkipPerFile) {
  Write-Output 'SUMMARY|per-file phase skipped (-SkipPerFile)'
  return
}

foreach ($parser in 'tree-sitter', 'DelphiAST') {
  $times = New-Object System.Collections.Generic.List[int]
  $peaks = New-Object System.Collections.Generic.List[int64]

  foreach ($f in $fixtures) {
    $rel = Convert-Rel $f.FullName

    if ($parser -eq 'tree-sitter') {
      $r = Invoke-Measured -Exe $TreeSitterExe -Arguments @('parse', $f.FullName) `
             -WorkingDirectory $GrammarDir -ExtraPath @($MingwBin)
    } else {
      $r = Invoke-Measured -Exe $DelphiASTHarness -Arguments @($f.FullName)
    }

    $times.Add($r.ElapsedMs)
    $peaks.Add($r.PeakWs)
    Write-Output ("PERFILE|{0}|{1}|elapsed_ms={2}|peak_ws_mb={3}|out_lines={4}" -f `
      $parser, $rel, $r.ElapsedMs, [math]::Round($r.PeakWs / 1MB, 2), $r.OutLines)
  }

  $total = ($times | Measure-Object -Sum).Sum
  $mean  = [math]::Round(($times | Measure-Object -Average).Average, 1)
  $maxP  = [math]::Round(($peaks | Measure-Object -Maximum).Maximum / 1MB, 2)
  Write-Output ("SUMMARY|parser={0}|files={1}|total_ms={2}|mean_ms={3}|max_peak_ws_mb={4}" -f `
    $parser, $fixtures.Count, $total, $mean, $maxP)
}
