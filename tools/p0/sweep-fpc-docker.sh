#!/usr/bin/env bash
#
# P0 sweep: compile every Pascal fixture in corpus/ with Free Pascal inside the
# pinned container image freepascal/fpc:3.2.2-bookworm-full.
#
# Methodologically identical to tools/p0/sweep-fpc.ps1 so that host and
# container results are directly comparable:
#   - fixtures  : *.pas, *.dpr, *.lpr
#   - mode      : first {$mode xxx} within the first 8 header lines, else fpc
#                 (default, i.e. what `fpc file.pas` does with no -M flag)
#   - isolation : a fresh -FE/-FU temp dir per fixture, so no stale .ppu/.o
#                 from an earlier fixture can influence a later one
#   - search    : -Fu/-Fi for every corpus subdirectory
#   - verdict   : first "<file>(<line>,<col>) Error|Fatal" line => FAIL
#                 (warnings never flip a verdict, matching the host sweep)
#
# Each fixture's verdict is additionally compared against the expectation
# declared in corpus/README.md. README expectations are platform-relative: it
# documents host (Windows) behavior, so the Linux-only adjustment for
# dbaccess/ado_style_connection.pas (unit ComObj is Windows-only) is applied
# here explicitly and called out in the output.
#
# Host invocation (repo mounted read-only; all compiler output goes to /tmp):
#   docker run --rm -v <repo>:/repo:ro freepascal/fpc:3.2.2-bookworm-full \
#     bash /repo/tools/p0/sweep-fpc-docker.sh
#
set -uo pipefail

REPO="${REPO:-/repo}"
CORPUS="$REPO/corpus"

if [ ! -d "$CORPUS" ]; then
  echo "FATAL|corpus not found at $CORPUS (is the repo mounted at /repo?)" >&2
  exit 2
fi

shopt -s nocasematch   # mirror PowerShell's case-insensitive -match

printf 'TOOL|%s|version=%s\n' "$(command -v fpc)" "$(fpc -iV 2>&1 | head -n 1)"
printf 'PLATFORM|%s\n' "$(uname -srm)"

# Expectation for a fixture, per corpus/README.md:
#   PASS             - compiles under the documented FPC mode
#   FAIL-DEPENDENCY  - must fail with a missing unit (expected, not a defect)
# Unit Forms (LCL) and unit DBTables (BDE) are never present in this image.
# Unit ComObj is Windows-only: PASS in the host sweep, FAIL-DEPENDENCY here.
expected() {
  local rel="$1"
  case "$rel" in
    applications/lazarus_app/lazarusapp.lpr) echo "FAIL-DEPENDENCY" ;;
    applications/lazarus_app/uMainForm.pas)  echo "FAIL-DEPENDENCY" ;;
    dbaccess/bde_style_query.pas)            echo "FAIL-DEPENDENCY" ;;
    dbaccess/ado_style_connection.pas)
      case "$(uname -s)" in
        Linux) echo "FAIL-DEPENDENCY" ;;
        *)     echo "PASS" ;;
      esac ;;
    *) echo "PASS" ;;
  esac
}

mapfile -t fixtures < <(
  cd "$CORPUS" &&
  find . -type f \( -name '*.pas' -o -name '*.dpr' -o -name '*.lpr' \) |
  sed 's|^\./||' | LC_ALL=C sort -f
)

# Every corpus subdirectory, excluding the corpus root itself (the host sweep
# uses Get-ChildItem -Recurse -Directory, which also excludes the root).
mapfile -t unitDirs < <(
  cd "$CORPUS" &&
  find . -mindepth 1 -type d | sed 's|^\./||' | LC_ALL=C sort -f
)

pass=0; fail=0; match=0; mismatch=0

for rel in "${fixtures[@]}"; do
  src="$CORPUS/$rel"

  # --- pick up the fixture's declared language mode (first 8 header lines) ---
  mode="fpc"
  n=0
  while [ "$n" -lt 8 ] && IFS= read -r line; do
    n=$((n + 1))
    if [[ "$line" =~ \{\$mode[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
      mode="${BASH_REMATCH[1]}"
      break
    fi
  done < "$src"

  tmp="$(mktemp -d /tmp/p0-fpc.XXXXXXXX)"

  args=("-M$mode" "-FE$tmp" "-FU$tmp" "-vew")
  for d in "${unitDirs[@]}"; do
    args+=("-Fu$CORPUS/$d" "-Fi$CORPUS/$d")
  done
  args+=("$src")

  out="$(fpc "${args[@]}" 2>&1)"
  err="$(printf '%s\n' "$out" |
    grep -m1 -E '^[[:space:]]*[^[:space:]]+\([0-9]+,[0-9]+\)[[:space:]]+(Error|Fatal)')"

  if [ -n "$err" ]; then
    status="FAIL"
    printf 'RESULT|FAIL|%s|%s|%s\n' "$mode" "$rel" "$err"
    fail=$((fail + 1))
  else
    status="PASS"
    printf 'RESULT|PASS|%s|%s\n' "$mode" "$rel"
    pass=$((pass + 1))
  fi

  # expected() speaks the README's vocabulary (PASS / FAIL-DEPENDENCY) while
  # status speaks the compiler's (PASS / FAIL). A declared FAIL-DEPENDENCY is
  # *satisfied* by a FAIL, so agreement is scored across the two vocabularies
  # rather than by string equality.
  exp="$(expected "$rel")"
  if [ "$exp" = "FAIL-DEPENDENCY" ]; then
    agreed=$([ "$status" = "FAIL" ] && echo yes || echo no)
  else
    agreed=$([ "$status" = "PASS" ] && echo yes || echo no)
  fi
  if [ "$agreed" = "yes" ]; then
    printf 'EXPECTATION|%s|expected=%s|actual=%s|MATCH\n' "$rel" "$exp" "$status"
    match=$((match + 1))
  else
    printf 'EXPECTATION|%s|expected=%s|actual=%s|MISMATCH\n' "$rel" "$exp" "$status"
    mismatch=$((mismatch + 1))
  fi

  rm -rf "$tmp"
done

printf 'SUMMARY|fixtures=%s|PASS=%s|FAIL=%s|MATCH=%s|MISMATCH=%s\n' \
  "${#fixtures[@]}" "$pass" "$fail" "$match" "$mismatch"
