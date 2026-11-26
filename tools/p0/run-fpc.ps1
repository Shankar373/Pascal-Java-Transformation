<#
  P0 run sweep: execute the programs produced by sweep-fpc.ps1 and record their
  observable behavior (exit code, stdout), so that corpus/README.md's promise
  that PASS means "compiles (and runs where a program)" is backed by evidence.

  This is the first, smallest step toward the P3 original-execution oracle: it
  captures what the ORIGINAL Pascal does, with no Java involved yet.

  Selection rules
    - only fixtures that compile (a run of a non-compiling fixture is not data)
    - only fixtures that produced an executable: units (.pas declaring "unit")
      compile to .ppu/.o and have nothing to run
    - fixtures whose header declares the runtime path out of scope are skipped
      explicitly, never silently: skipped lines carry the reason

  Verdict rules
    - a program that starts and terminates is recorded with its real exit code
      and first stdout line. A non-zero exit is NOT a failure here: several
      fixtures assert exit codes on purpose (exception_flow halts with 2).
      Timeout is the only run-level failure.
    - file_io.pas requires a destination path (ParamStr(1)); it is given a temp
      path so its real read/write path is exercised rather than its usage text.

  Output (stdout, one line per fixture considered):
    RUN|<relpath>|exit=<n>|ms=<n>|out=<first stdout line>
    RUN|<relpath>|TIMEOUT|killed after <n> ms
    SKIP|<relpath>|<reason>

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools/p0/run-fpc.ps1 `
        [-FpcPath <fpc.exe>] [-Corpus <dir>] [-TimeoutSec 10]
#>
[CmdletBinding()]
param(
  [string]$FpcPath = 'C:\FPC\3.2.2\bin\i386-Win32\fpc.exe',
  [string]$Corpus,
  [int]$TimeoutSec = 10
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus) { $Corpus = Join-Path $PSScriptRoot '..\..\corpus' }
$Corpus = (Resolve-Path -LiteralPath $Corpus).Path
if (-not (Test-Path -LiteralPath $FpcPath)) { throw "fpc not found at '$FpcPath'." }

# Shared MSVC-convention argument quoter; must be loaded in the body (not in a
# param() default) because $PSScriptRoot is not populated there.
. (Join-Path $PSScriptRoot 'NativeArgument.ps1')

# Fixtures whose header explicitly puts the runtime path out of scope.
$compileOnly = @{
  'dbaccess\ado_style_connection.pas' = 'header: compile-only, no ADO provider registered; runtime path not exercised'
}

$fixtures = Get-ChildItem -LiteralPath $Corpus -Recurse -File |
  Where-Object { $_.Extension -in '.pas', '.dpr', '.lpr' } |
  Sort-Object FullName

$unitDirs = Get-ChildItem -LiteralPath $Corpus -Recurse -Directory | ForEach-Object { $_.FullName }

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('p0-run-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmpRoot | Out-Null

try {
  foreach ($f in $fixtures) {
    $rel = $f.FullName.Substring($Corpus.Length + 1)

    $mode = 'fpc'
    $head = Get-Content -Path $f.FullName -TotalCount 8 -ErrorAction SilentlyContinue
    foreach ($line in $head) {
      if ($line -match '\{\$mode\s+(\w+)') { $mode = $Matches[1]; break }
    }

    $out = Join-Path $tmpRoot ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $out | Out-Null

    $fpcArgs = @("-M$mode", "-FE$out", "-FU$out", '-vew')
    foreach ($d in $unitDirs) { $fpcArgs += "-Fu$d"; $fpcArgs += "-Fi$d" }
    $fpcArgs += $f.FullName

    $cOut = @(& $FpcPath @fpcArgs 2>&1 | ForEach-Object { "$_" })
    $cErr = $cOut | Where-Object { $_ -match '^\s*\S+\((\d+),(\d+)\)\s+(Error|Fatal)' } |
              Select-Object -First 1

    if ($cErr) {
      # Not a run result: the fixture never built. Record it so the gap between
      # the compile sweep and this run sweep is visible rather than implied.
      Write-Output "SKIP|$rel|did not compile: $($cErr.Trim())"
      continue
    }

    $exe = Get-ChildItem -LiteralPath $out -Filter '*.exe' -File -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if (-not $exe) {
      Write-Output "SKIP|$rel|unit (no executable produced; nothing to run)"
      continue
    }

    if ($compileOnly.ContainsKey($rel)) {
      Write-Output "SKIP|$rel|$($compileOnly[$rel])"
      continue
    }

    # file_io.pas wants an output path; give it a real one instead of its
    # usage/exit-1 branch so the read/write path is what gets measured.
    $runArgs = @()
    if ($rel -like '*file_io.pas') {
      $runArgs += (Join-Path $out 'file_io_out.txt')
    }

    # Start-Process -PassThru yields a Process whose ExitCode stays null even
    # after Refresh()/HasExited, so process exit status is read through the raw
    # .NET API instead (verified: same binary reports exit=2 via .NET and null
    # via Start-Process).
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $exe.FullName
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    # PS 5.1 runs on .NET Framework, where ProcessStartInfo has no ArgumentList
    # collection - only the Arguments string. The single path argument is quoted
    # with the shared MSVC-convention quoter rather than '"' + $arg + '"', which
    # mishandles an embedded quote or a trailing backslash (see NativeArgument.ps1).
    if ($runArgs.Count -gt 0) {
      $psi.Arguments = ConvertTo-NativeArgument -ArgumentList $runArgs
    }

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $run = [System.Diagnostics.Process]::Start($psi)
    $stdoutTask = $run.StandardOutput.ReadToEndAsync()
    $stderrTask = $run.StandardError.ReadToEndAsync()
    if (-not $run.WaitForExit($TimeoutSec * 1000)) {
      try { $run.Kill() } catch { }
      Write-Output "RUN|$rel|TIMEOUT|killed after $($TimeoutSec * 1000) ms"
      continue
    }
    $run.WaitForExit()          # flush async readers after the bounded wait
    $exitCode = $run.ExitCode
    $sw.Stop()

    $stdoutText = $stdoutTask.Result
    $stdoutLines = @()
    if ($stdoutText) { $stdoutLines = @($stdoutText -split "\r?\n" | Where-Object { $_ -ne '' }) }
    $first = ''
    if ($stdoutLines.Count -gt 0) { $first = $stdoutLines[0] }

    Write-Output ('RUN|{0}|exit={1}|ms={2}|out={3}' -f `
      $rel, $exitCode, [int]$sw.ElapsedMilliseconds, $first)
  }
} finally {
  Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
}
