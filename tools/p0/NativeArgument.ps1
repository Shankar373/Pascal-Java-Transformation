<#
  Native argument quoting for ProcessStartInfo.Arguments (Windows).

  WHY THIS EXISTS
  ---------------
  PowerShell 5.1 runs on .NET Framework, where ProcessStartInfo has no
  ArgumentList collection - only the Arguments string. Scripts that need a
  real exit code (measure-parsers.ps1, run-fpc.ps1) must use the raw .NET
  Process API, because Start-Process -PassThru reports ExitCode as null even
  after Refresh()/HasExited. Building that string by hand as

      '"' + $arg + '"'

  is wrong in two ways:

    1. an embedded double quote terminates the argument early;
    2. a trailing backslash escapes the closing quote - `"C:\dir\"` is read
       as the single token `C:\dir"` .

  Both are unreachable for the P0 golden corpus (Windows forbids `"` in file
  names, and a file name cannot end in `\`), which is why this was logged as
  LOW. It is fixed now because P1 ingests untrusted archive paths, where
  neither precondition holds.

  THE RULE
  --------
  This is the MSVC / CommandLineToArgvW convention. For each argument:

    - backslashes are literal unless they precede a double quote;
    - N backslashes followed by `"` become 2N backslashes followed by `\"`;
    - N trailing backslashes (before the closing quote) become 2N, so they
      cannot escape it;
    - the argument is always quoted, which also preserves an empty argument.

  Dot-source this file from a script body (not from a param() default, where
  $PSScriptRoot is not yet populated):

      . (Join-Path $PSScriptRoot 'NativeArgument.ps1')

  Kept in one place so the two consumers cannot drift apart.
#>

function ConvertTo-NativeArgument {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [AllowEmptyCollection()]
    [AllowEmptyString()]
    [string[]]$ArgumentList
  )

  $quoted = foreach ($arg in $ArgumentList) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')

    $backslashes = 0
    foreach ($ch in $arg.ToCharArray()) {
      if ($ch -eq '\') { $backslashes++; continue }
      if ($ch -eq '"') {
        # 2N+1 backslashes before a quote -> 2N backslashes, then an escaped quote.
        if ($backslashes -gt 0) { [void]$sb.Append(('\' * ($backslashes * 2)) -join '') }
        [void]$sb.Append('\"')
      } else {
        if ($backslashes -gt 0) { [void]$sb.Append(('\' * $backslashes) -join '') }
        [void]$sb.Append($ch)
      }
      $backslashes = 0
    }
    # Trailing backslashes must be doubled so they do not escape our closing quote.
    if ($backslashes -gt 0) { [void]$sb.Append(('\' * ($backslashes * 2)) -join '') }

    [void]$sb.Append('"')
    $sb.ToString()
  }

  return ($quoted -join ' ')
}
