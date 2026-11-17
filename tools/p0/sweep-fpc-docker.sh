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
# Each fixture's verdict is compared against corpus/expectations.txt - the
# single source of truth shared with tools/p1/sweep.py, so the host sweep and
# this container sweep are scored against the same contract.  Platform-relative
# expectations (e.g. dbaccess/ado_style_connection.pas, whose unit ComObj is
# Windows-only) are declared as `linux=` overrides in that file and applied
# here from `uname -s`.
#
# Exit status: 0 = every expectation matched, 1 = at least one MISMATCH,
# 2 = the sweep could not run (missing corpus, missing or malformed
# expectations).  MISMATCH therefore fails CI rather than being reported and
# ignored.
#
# Host invocation (repo mounted read-only; all compiler output goes to /tmp):
#   docker run --rm -v <repo>:/repo:ro freepascal/fpc:3.2.2-bookworm-full \
#     bash /repo/tools/p0/sweep-fpc-docker.sh
#
# Archive mode (A4): pass --baseline <file> to retain this run's report.  The
# path must be writable inside the container (the /repo mount is read-only),
# so point it at a second read-write mount, or archive the host-side report
# with `python tools/p1/sweep.py --host --out <file>`.
#
set -uo pipefail

REPO="${REPO:-/repo}"
CORPUS="$REPO/corpus"
EXPECT_FILE="$CORPUS/expectations.txt"
BASELINE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --baseline)
      [ $# -ge 2 ] || { echo "FATAL|--baseline needs a path" >&2; exit 2; }
      BASELINE="$2"; shift 2 ;;
    *)
      echo "FATAL|unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Archive mode (A4): buffer the report so the retained baseline is byte-
# identical to what stdout would have carried.  Done before the first report
# line is printed, so nothing is lost.
REPORT_FILE=""
if [ -n "$BASELINE" ]; then
  REPORT_FILE="$(mktemp /tmp/p0-report.XXXXXXXX)" ||
    { echo "FATAL|cannot create a report buffer" >&2; exit 2; }
  exec 3>&1          # hold the real stdout so the buffered report can be
  exec >"$REPORT_FILE"   # replayed (and archived) at the end
fi

if [ ! -d "$CORPUS" ]; then
  echo "FATAL|corpus not found at $CORPUS (is the repo mounted at /repo?)" >&2
  exit 2
fi

if [ ! -f "$EXPECT_FILE" ]; then
  echo "FATAL|expectations not found at $EXPECT_FILE" >&2
  exit 2
fi

# Platform key used to resolve the override column of an expectation.
case "$(uname -s)" in
  Linux)                 OS="linux" ;;
  MINGW*|MSYS*|CYGWIN*)  OS="windows" ;;
  *)                     OS="$(uname -s | tr '[:upper:]' '[:lower:]')" ;;
esac

shopt -s nocasematch   # mirror PowerShell's case-insensitive -match

printf 'TOOL|%s|version=%s\n' "$(command -v fpc)" "$(fpc -iV 2>&1 | head -n 1)"
printf 'PLATFORM|%s\n' "$(uname -srm)"

# Load corpus/expectations.txt into EXPECTED[rel]=verdict.  The file is the
# single source of truth; a malformed or empty table is a hard error (exit 2)
# so a broken contract can never degrade into "everything matches".
declare -A EXPECTED=()
while IFS= read -r raw || [ -n "$raw" ]; do
  line="${raw%$'\r'}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  case "$line" in ''|'#'*) continue ;; esac

  IFS='|' read -r rel base rest <<<"$line"
  rel="${rel//\\//}"
  if [ -z "${rel:-}" ] || [ -z "${base:-}" ]; then
    echo "FATAL|expectations: malformed line: $raw" >&2
    exit 2
  fi
  case "$base" in
    PASS|FAIL-DEPENDENCY) ;;
    *) echo "FATAL|expectations: bad verdict $base for $rel" >&2; exit 2 ;;
  esac

  verdict="$base"
  if [ -n "${rest:-}" ]; then
    IFS=',' read -ra overrides <<<"$rest"
    for entry in "${overrides[@]}"; do
      entry="${entry#"${entry%%[![:space:]]*}"}"
      entry="${entry%"${entry##*[![:space:]]}"}"
      [ -z "$entry" ] && continue
      key="${entry%%=*}"
      value="${entry#*=}"
      key="$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')"
      case "$value" in
        PASS|FAIL-DEPENDENCY) ;;
        *) echo "FATAL|expectations: bad override $entry for $rel" >&2; exit 2 ;;
      esac
      if [ "$key" = "$OS" ]; then verdict="$value"; fi
    done
  fi

  if [ -n "${EXPECTED[$rel]+x}" ]; then
    echo "FATAL|expectations: duplicate entry for $rel" >&2
    exit 2
  fi
  EXPECTED[$rel]="$verdict"
done <"$EXPECT_FILE"

if [ "${#EXPECTED[@]}" -eq 0 ]; then
  echo "FATAL|expectations: $EXPECT_FILE declares no fixtures" >&2
  exit 2
fi

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
declare -A SWEPT=()

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

  SWEPT[$rel]=1

  # The expectation table speaks the README's vocabulary (PASS /
  # FAIL-DEPENDENCY) while status speaks the compiler's (PASS / FAIL).  A
  # declared FAIL-DEPENDENCY is *satisfied* by a FAIL, so agreement is scored
  # across the two vocabularies rather than by string equality.  A fixture
  # with no declared expectation is itself a MISMATCH: the corpus and the
  # contract must move together.
  if [ -z "${EXPECTED[$rel]+x}" ]; then
    printf 'EXPECTATION|%s|expected=UNDECLARED|actual=%s|MISMATCH\n' "$rel" "$status"
    mismatch=$((mismatch + 1))
  else
    exp="${EXPECTED[$rel]}"
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
  fi

  rm -rf "$tmp"
done

# An expectation with no fixture means the corpus lost a file (or this sweep
# stopped early).  Report it instead of letting the table shrink silently.
for rel in "${!EXPECTED[@]}"; do
  if [ -z "${SWEPT[$rel]+x}" ]; then
    printf 'EXPECTATION|%s|expected=%s|actual=NOT-SWEPT|MISMATCH\n' \
      "$rel" "${EXPECTED[$rel]}"
    mismatch=$((mismatch + 1))
  fi
done

printf 'SUMMARY|fixtures=%s|PASS=%s|FAIL=%s|MATCH=%s|MISMATCH=%s\n' \
  "${#fixtures[@]}" "$pass" "$fail" "$match" "$mismatch"

if [ -n "$REPORT_FILE" ]; then
  exec >&3           # restore the real stdout before replaying the report
  cat "$REPORT_FILE"
  if ! cp "$REPORT_FILE" "$BASELINE" 2>/dev/null; then
    echo "FATAL|cannot write baseline at $BASELINE" >&2
    rm -f "$REPORT_FILE"
    exit 2
  fi
  rm -f "$REPORT_FILE"
fi

if [ "$mismatch" -gt 0 ]; then
  exit 1
fi
exit 0
