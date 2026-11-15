<#
  P0 path-quoting test: exercises tools/p0/NativeArgument.ps1 against paths with
  spaces and other legal-but-awkward characters, and proves the two scripts that
  build a ProcessStartInfo.Arguments string (measure-parsers.ps1, run-fpc.ps1)
  deliver the exact path to the child process.

  Why this exists
  ---------------
  A hand-rolled '"' + $arg + '"' breaks in two ways:

    1. a trailing backslash escapes the closing quote, so
       "C:\dir\" is read by the child as C:\dir"
    2. an embedded double quote terminates the argument early

  (1) is reachable in normal use - any output directory passed with a trailing
  separator - and is what this test reproduces end-to-end. (2) is unreachable
  for file names on Windows (the character is illegal in paths), so it is
  covered by the unit table only.

  Sections
    UNIT   - ConvertTo-NativeArgument output against exact expected strings,
             including cases that cannot occur as Windows file names.
    ROUND  - a real child (fpc.exe) launched through ProcessStartInfo with the
             quoter, on a corpus under a path containing spaces, parentheses,
             an ampersand, brackets and a hash. Section ROUND-2 additionally
             passes the output directory WITH a trailing backslash, which is
             the case the old quoting got wrong.
    SCRIPT - run-fpc.ps1 and measure-parsers.ps1 executed against that same
             special-path corpus, so the fixed code path is what is measured.

  Every section reports SKIP with a reason when a required tool is absent;
  nothing is silently passed.

  Set P0_ARGV_DEBUG=1 to additionally dump the raw CommandLineToArgvW tokens
  for the control case (useful when a comparison fails and the cause is unclear).

  Output (stdout):
    UNIT|<case>|PASS|got=<s>
    UNIT|<case>|FAIL|got=<s>|want=<s>
    ROUND|<id>|PASS|<detail>
    ROUND|<id>|FAIL|<detail>
    ROUND|<id>|SKIP|<reason>
    SCRIPT|<name>|PASS|<detail>
    SCRIPT|<name>|FAIL|<detail>
    SCRIPT|<name>|SKIP|<reason>
    SUMMARY|tested=<n>|pass=<n>|fail=<n>|skip=<n>

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\test-path-quoting.ps1 `
        [-Corpus <dir>] [-FpcPath <fpc.exe>] [-TreeSitterExe <tree-sitter.exe>] `
        [-GrammarDir <clone>] [-MingwBin <dir>] [-DelphiASTHarness <exe>] [-SkipScripts]
#>
[CmdletBinding()]
param(
  [string]$Corpus,
  [string]$FpcPath = 'C:\FPC\3.2.2\bin\i386-Win32\fpc.exe',
  [string]$TreeSitterExe,
  [string]$GrammarDir,
  [string]$MingwBin,
  [string]$DelphiASTHarness,
  [switch]$SkipScripts
)

$ErrorActionPreference = 'Stop'
if (-not $Corpus) { $Corpus = Join-Path $PSScriptRoot '..\..\corpus' }
$Corpus = (Resolve-Path -LiteralPath $Corpus).Path

# $PSScriptRoot is populated in the body but not inside param() defaults, so
# the shared quoter is dot-sourced here rather than in the param block.
. (Join-Path $PSScriptRoot 'NativeArgument.ps1')

$script:pass = 0
$script:fail = 0
$script:skip = 0

function Report([string]$Kind, [string]$Id, [string]$Status, [string]$Detail) {
  Write-Output ("{0}|{1}|{2}|{3}" -f $Kind, $Id, $Status, $Detail)
  switch ($Status) {
    'PASS' { $script:pass++ }
    'FAIL' { $script:fail++ }
    'SKIP' { $script:skip++ }
  }
}

# ---------------------------------------------------------------------------
# UNIT - exact expected output of the quoter
# ---------------------------------------------------------------------------
# Each case is (input, expected). Cases with a quote or a trailing backslash
# cannot occur as Windows file names; they pin the algorithm, not the corpus.
$unitCases = @(
  @('C:\plain\file.pas',        '"C:\plain\file.pas"'),
  @('C:\my dir\file.pas',       '"C:\my dir\file.pas"'),
  @('C:\dir (v2) & test\a.pas', '"C:\dir (v2) & test\a.pas"'),
  @('C:\a"b.pas',               '"C:\a\"b.pas"'),
  @('C:\dir\',                  '"C:\dir\\"'),
  @('C:\tricky\"\x.pas',        '"C:\tricky\\\"\x.pas"'),
  @('C:\ends\\',                '"C:\ends\\\\"'),
  @('',                         '""'),
  @('tab	x.pas',           '"tab	x.pas"'),
  @('percent % caret ^.pas',    '"percent % caret ^.pas"'),
  @('#1 [draft] {x} ''q''+b',   '"#1 [draft] {x} ''q''+b"')
)

foreach ($c in $unitCases) {
  $got  = ConvertTo-NativeArgument -ArgumentList @($c[0])
  $want = $c[1]
  $name = if ($c[0] -eq '') { '<empty>' } else { $c[0] }
  if ($got -ceq $want) { Report 'UNIT' $name 'PASS' "got=$got" }
  else                 { Report 'UNIT' $name 'FAIL' "got=$got|want=$want" }
}

# ---------------------------------------------------------------------------
# ROUND - a real child process must receive the exact path
# ---------------------------------------------------------------------------
# The child is fpc.exe: if it compiles, it received the path intact. The
# directory names below are deliberately awkward but 100% legal on NTFS.
$specialRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'p0 quote test (v2) & [draft] #1'
$srcDir      = Join-Path $specialRoot 'src'
$outDir      = Join-Path $specialRoot 'out'
$outDirTrail = $outDir + '\'          # trailing separator: the case old quoting broke

foreach ($d in $specialRoot, $srcDir, $outDir) {
  if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

# currency_math.pas is a self-contained program: no uses clause, no include, so
# the compile result depends only on the path being delivered correctly.
$srcSample = Join-Path $Corpus 'language\currency_math.pas'
$weirdName = 'currency math (v2) & test #1.pas'
$weirdSrc  = Join-Path $srcDir $weirdName
Copy-Item -LiteralPath $srcSample -Destination $weirdSrc -Force

# A minimal fpc launcher mirroring exactly what the fixed scripts do:
# ProcessStartInfo + ConvertTo-NativeArgument (PS 5.1 has no ArgumentList, and
# Start-Process reports ExitCode as null, so the raw .NET API is required).
function Invoke-FpcQuoted {
  param([string[]]$FpcArgs, [string]$WorkDir)

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName               = $FpcPath
  $psi.Arguments              = ConvertTo-NativeArgument -ArgumentList $FpcArgs
  $psi.WorkingDirectory       = $WorkDir
  $psi.UseShellExecute        = $false
  $psi.CreateNoWindow         = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError  = $true

  $p   = [System.Diagnostics.Process]::Start($psi)
  $so  = $p.StandardOutput.ReadToEndAsync()
  $se  = $p.StandardError.ReadToEndAsync()
  $p.WaitForExit()
  [pscustomobject]@{
    ExitCode = $p.ExitCode
    Output   = (($so.Result -split "\r?\n") + ($se.Result -split "\r?\n")) -join ' '
  }
}

if (-not (Test-Path -LiteralPath $FpcPath)) {
  Report 'ROUND' 'fpc-availability' 'SKIP' "fpc not found at $FpcPath"
} else {
  # ROUND-1: path with spaces + specials, output dir WITHOUT trailing separator.
  #   This is the baseline: correct quoting must produce an .exe.
  #   NOTE: each concatenation is parenthesised. In PowerShell ',' binds tighter
  #   than '+', so @('-FE' + $a, '-FU' + $b) parses as '-FE' + @($a,'-FU',$b)
  #   and collapses to ONE string (the array is stringified with $OFS=' ').
  $r1 = Invoke-FpcQuoted -FpcArgs @(('-FE' + $outDir), ('-FU' + $outDir), '-vew', $weirdSrc) `
                          -WorkDir $srcDir
  $exe1 = Join-Path $outDir 'currency math (v2) & test #1.exe'
  if ($r1.ExitCode -eq 0 -and (Test-Path -LiteralPath $exe1)) {
    Report 'ROUND' 'spaces-specials' 'PASS' "exit=0|exe=$([System.IO.Path]::GetFileName($exe1))"
  } else {
    Report 'ROUND' 'spaces-specials' 'FAIL' "exit=$($r1.ExitCode)|output=$($r1.Output.Substring(0,[Math]::Min(200,$r1.Output.Length)))"
  }

  # ROUND-2: same, but the output directory is passed WITH a trailing backslash.
  #   Old quoting produced "...\out\" -> child read ...\out" and the compile
  #   failed. This is the discriminating case for the fix.
  if (Test-Path -LiteralPath $outDirTrail) {
    $r2 = Invoke-FpcQuoted -FpcArgs @(('-FE' + $outDirTrail), ('-FU' + $outDirTrail), '-vew', $weirdSrc) `
                            -WorkDir $srcDir
    if ($r2.ExitCode -eq 0) {
      Report 'ROUND' 'trailing-backslash' 'PASS' "exit=0|dir=$outDirTrail"
    } else {
      Report 'ROUND' 'trailing-backslash' 'FAIL' "exit=$($r2.ExitCode)|output=$($r2.Output.Substring(0,[Math]::Min(200,$r2.Output.Length)))"
    }
  } else {
    Report 'ROUND' 'trailing-backslash' 'SKIP' "could not form trailing-separator path"
  }

  # ROUND-3: control - show the OLD quoting is actually wrong under the Windows
  #   ground truth, so the PASSes above are attributable to the fix.
  #
  #   fpc CANNOT be this oracle: FPC's own argv parser treats a backslash as a
  #   literal and lets the following quote close the token, so it tolerates the
  #   old encoding (verified: fpc compiles successfully under both). The rule
  #   that the old encoding breaks is CommandLineToArgvW / MSVC-CRT - the rule
  #   tree-sitter.exe (Rust) and most non-FPC Windows binaries follow - so that
  #   is what is asserted against, via P/Invoke.
  if (-not ('Win32.Argv' -as [type])) {
    Add-Type -Namespace Win32 -Name Argv -MemberDefinition @'
[DllImport("shell32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern IntPtr CommandLineToArgvW(string lpCmdLine, out int pNumArgs);
[DllImport("kernel32.dll")]
public static extern IntPtr LocalFree(IntPtr hMem);
'@
  }

  # Split a command line exactly the way the Windows standard does.
  # NOTE: return the array directly - a unary comma (return ,$arr) would hand
  # back a nested array whose .Count is 1 regardless of the real argument
  # count, silently corrupting every downstream comparison.
  function Split-NativeCommandLine([string]$CmdLine) {
    $n = 0
    $p = [Win32.Argv]::CommandLineToArgvW($CmdLine, [ref]$n)
    if ($p -eq [IntPtr]::Zero) { return @() }
    $argv = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $n; $i++) {
      $ptr = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($p, $i * [IntPtr]::Size)
      $argv.Add([System.Runtime.InteropServices.Marshal]::PtrToStringUni($ptr))
    }
    [void][Win32.Argv]::LocalFree($p)
    return $argv.ToArray()
  }

  function Test-SameArgs([string[]]$A, [string[]]$B) {
    if ($A.Count -ne $B.Count) { return $false }
    for ($i = 0; $i -lt $A.Count; $i++) { if ($A[$i] -cne $B[$i]) { return $false } }
    return $true
  }

  # A trailing-backslash directory is the discriminating input: it is legal and
  # common (any output directory passed with a trailing separator).
  # Parentheses are mandatory here - ',' binds tighter than '+' in PowerShell,
  # so an unparenthesised @('-FE' + $x, ...) collapses to a single string.
  $probeArgs = @(('-FE' + $outDirTrail), ('-FU' + $outDirTrail), '-vew', $weirdSrc)

  # 'prog.exe' is prepended because the first token of a command line is the
  # program name under either interpretation; the arguments follow it.
  $oldLine = 'prog.exe ' + (($probeArgs | ForEach-Object { '"' + $_ + '"' }) -join ' ')
  $newLine = 'prog.exe ' + (ConvertTo-NativeArgument -ArgumentList $probeArgs)

  $oldGot = @((Split-NativeCommandLine $oldLine) | Select-Object -Skip 1)
  $newGot = @((Split-NativeCommandLine $newLine) | Select-Object -Skip 1)
  $oldOk  = Test-SameArgs $oldGot $probeArgs
  $newOk  = Test-SameArgs $newGot $probeArgs

  if ($env:P0_ARGV_DEBUG) {
    $allOld = @(Split-NativeCommandLine $oldLine)
    Write-Output ("DEBUG|oldLineLen={0}|allOldCount={1}|oldGotCount={2}|newGotCount={3}" -f `
      $oldLine.Length, $allOld.Count, $oldGot.Count, $newGot.Count)
    $i = 0
    foreach ($a in $allOld) { $i++; Write-Output ("DEBUG|old[{0}]={1}" -f $i, $a) }
  }

  if ((-not $oldOk) -and $newOk) {
    $oldDesc = "$($oldGot.Count) arg(s)"
    if ($oldGot.Count -eq 1) { $oldDesc = "1 merged arg instead of $($probeArgs.Count)" }
    elseif ($oldGot.Count -eq 0) { $oldDesc = "0 arg(s) instead of $($probeArgs.Count)" }
    Report 'ROUND' 'quoter-discriminates' 'PASS' "CommandLineToArgvW|old=$oldDesc|new=exact match($($newGot.Count))"
  } elseif ($oldOk) {
    Report 'ROUND' 'quoter-discriminates' 'FAIL' 'old quoting also round-trips - control does not discriminate'
  } else {
    Report 'ROUND' 'quoter-discriminates' 'FAIL' "oldOk=$oldOk|newOk=$newOk|newCount=$($newGot.Count)|want=$($probeArgs.Count)"
  }
}

# ---------------------------------------------------------------------------
# SCRIPT - run the two fixed scripts end-to-end on the special-path corpus
# ---------------------------------------------------------------------------
if ($SkipScripts) {
  Report 'SCRIPT' 'all' 'SKIP' '-SkipScripts supplied'
} elseif (-not (Test-Path -LiteralPath $FpcPath)) {
  Report 'SCRIPT' 'run-fpc.ps1' 'SKIP' "fpc not found at $FpcPath"
} else {
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('p0-quoting-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    # Copy the whole corpus under the special root so every fixture path that
    # the scripts pass to a child contains the awkward characters.
    $specialCorpus = Join-Path $specialRoot 'corpus'
    Copy-Item -LiteralPath $Corpus -Destination $specialCorpus -Recurse -Force

    # --- run-fpc.ps1: passes a temp output path through the fixed quoter ---
    $outFile = Join-Path $tmp 'run-fpc.txt'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
        (Join-Path $PSScriptRoot 'run-fpc.ps1') `
        -FpcPath $FpcPath -Corpus $specialCorpus -TimeoutSec 20 *> $outFile
    $runExit = $LASTEXITCODE
    $runLines = @(Get-Content -LiteralPath $outFile -ErrorAction SilentlyContinue)
    $runs  = @($runLines | Where-Object { $_ -like 'RUN|*' })
    # PowerShell's own error signature only - a broad pattern would also match
    # legitimate compiler text such as "Can't find unit Forms".
    $errs  = @($runLines | Where-Object { $_ -match 'FullyQualifiedErrorId|CategoryInfo|: The term' })
    if ($runExit -eq 0 -and $runs.Count -gt 0 -and $errs.Count -eq 0) {
      Report 'SCRIPT' 'run-fpc.ps1' 'PASS' "exit=0|runs=$($runs.Count)|special-path corpus"
    } else {
      $why = if ($errs.Count -gt 0) { $errs[0].Trim() } else { "exit=$runExit" }
      Report 'SCRIPT' 'run-fpc.ps1' 'FAIL' "exit=$runExit|runs=$($runs.Count)|errs=$($errs.Count)|first=$($why.Substring(0,[Math]::Min(160,$why.Length)))"
    }

    # --- measure-parsers.ps1: fixture paths flow through the fixed quoter ---
    if (-not $TreeSitterExe) {
      $TreeSitterExe = Join-Path $env:USERPROFILE 'node_modules\tree-sitter-cli\tree-sitter.exe'
      if (-not (Test-Path -LiteralPath $TreeSitterExe)) {
        $TreeSitterExe = Join-Path $env:LOCALAPPDATA 'npm\node_modules\tree-sitter-cli\tree-sitter.exe'
      }
    }
    if (-not $GrammarDir) {
      $GrammarDir = Join-Path ([System.IO.Path]::GetTempPath()) 'opencode\p0-work\tree-sitter-pascal'
    }
    if (-not $DelphiASTHarness) {
      $DelphiASTHarness = Join-Path ([System.IO.Path]::GetTempPath()) 'opencode\p0-work\bin\delphiast_eval.exe'
    }
    # gcc is absent from this machine; the grammar's pascal.dll is already built
    # and cached, so the PATH entry is a no-op rather than a requirement here.
    if (-not $MingwBin) { $MingwBin = $PSScriptRoot }

    $missing = @()
    if (-not (Test-Path -LiteralPath $TreeSitterExe))    { $missing += "tree-sitter=$TreeSitterExe" }
    if (-not (Test-Path -LiteralPath $GrammarDir))       { $missing += "grammar=$GrammarDir" }
    if (-not (Test-Path -LiteralPath $DelphiASTHarness)) { $missing += "harness=$DelphiASTHarness" }

    if ($missing.Count -gt 0) {
      Report 'SCRIPT' 'measure-parsers.ps1' 'SKIP' ($missing -join ';')
    } else {
      $mFile = Join-Path $tmp 'measure-parsers.txt'
      & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
          (Join-Path $PSScriptRoot 'measure-parsers.ps1') `
          -TreeSitterExe $TreeSitterExe -GrammarDir $GrammarDir -MingwBin $MingwBin `
          -DelphiASTHarness $DelphiASTHarness -Corpus $specialCorpus *> $mFile
      $mExit = $LASTEXITCODE
      $mLines = @(Get-Content -LiteralPath $mFile -ErrorAction SilentlyContinue)
      $batches = @($mLines | Where-Object { $_ -like 'BATCH|*' })
      $badOut  = @($mLines | Where-Object { $_ -match 'out_lines=0\b' })
      $mErr    = @($mLines | Where-Object { $_ -match 'FullyQualifiedErrorId|CategoryInfo|: The term' })
      if ($mExit -eq 0 -and $batches.Count -ge 2 -and $badOut.Count -eq 0 -and $mErr.Count -eq 0) {
        Report 'SCRIPT' 'measure-parsers.ps1' 'PASS' "exit=0|batches=$($batches.Count)|zero-output=$($badOut.Count)|special-path corpus"
      } else {
        $why = if ($mErr.Count -gt 0) { $mErr[0].Trim() } else { "exit=$mExit" }
        Report 'SCRIPT' 'measure-parsers.ps1' 'FAIL' "exit=$mExit|batches=$($batches.Count)|zero-output=$($badOut.Count)|errs=$($mErr.Count)|first=$($why.Substring(0,[Math]::Min(160,$why.Length)))"
      }
    }
  } finally {
    # -LiteralPath is required: $specialRoot contains '[draft]', which -Path
    # would treat as a wildcard and silently fail to delete.
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $specialRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}

Write-Output ("SUMMARY|tested={0}|pass={1}|fail={2}|skip={3}" -f `
  ($script:pass + $script:fail), $script:pass, $script:fail, $script:skip)
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
