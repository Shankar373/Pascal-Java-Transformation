<#
  P1 gate runner - every check that must pass before P1 is called complete.

  Gates, in order (each must exit 0; the runner stops reporting only after
  all of them have run, so one failure does not hide the rest):

    1. tests       python -m pytest tests -q          unit + integration + security
    2. guard       python tools/p1/cli.py guard --root .   the no-LLM guard
    3. host sweep  python tools/p1/sweep.py --host     FPC on this machine
    4. container   python tools/p1/sweep.py --docker   pinned image, digest-pinned

  Gates 3 and 4 score every fixture in corpus/ against corpus/expectations.txt
  (task E5).  A new MISMATCH, an undeclared fixture or an expectation whose
  fixture has gone missing all exit non-zero.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\p1\run_gates.ps1
      [-SkipContainer] [-SkipSweep]

  -SkipContainer / -SkipSweep exist for machines without Docker or without a
  local FPC.  They are a local convenience only: CI runs all four gates and
  does not pass them.  A skipped gate is printed as SKIP, never as PASS.
#>
[CmdletBinding()]
param(
  [switch]$SkipContainer,
  [switch]$SkipSweep
)

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $repo
try {
  $failures = New-Object System.Collections.Generic.List[string]
  $skips = New-Object System.Collections.Generic.List[string]

  function Invoke-Gate {
    param([string]$Name, [scriptblock]$Body)

    Write-Host ''
    Write-Host "==> $Name"
    $global:LASTEXITCODE = 0
    try {
      & $Body
      $code = $global:LASTEXITCODE
      if ($code -ne 0) { throw "exit code $code" }
      Write-Host "==> $Name : PASS"
    } catch {
      Write-Host "==> $Name : FAIL - $($_.Exception.Message)"
      [void]$script:failures.Add($Name)
    }
  }

  Invoke-Gate 'tests (unit + integration + security)' {
    python -m pytest tests -q
  }

  Invoke-Gate 'no-LLM guard' {
    python tools/p1/cli.py guard --root .
  }

  if ($SkipSweep) {
    Write-Host ''
    Write-Host '==> fixture sweep (host FPC): SKIP - explicitly requested'
    [void]$skips.Add('host-sweep')
  } else {
    Invoke-Gate 'fixture sweep (host FPC)' {
      python tools/p1/sweep.py --host
    }
  }

  if ($SkipSweep -or $SkipContainer) {
    Write-Host ''
    Write-Host '==> fixture sweep (pinned container): SKIP - explicitly requested'
    [void]$skips.Add('container-sweep')
  } else {
    Invoke-Gate 'fixture sweep (pinned container)' {
      python tools/p1/sweep.py --docker
    }
  }

  Write-Host ''
  if ($skips.Count -gt 0) {
    Write-Host "GATE|SKIP|$($skips -join ',') - CI runs the skipped gate(s)"
  }
  if ($failures.Count -gt 0) {
    Write-Host "GATE|FAIL|failed=$($failures.Count) :: $($failures -join ', ')"
    exit 1
  }
  Write-Host 'GATE|PASS|all gates green'
  exit 0
} finally {
  Pop-Location
}
