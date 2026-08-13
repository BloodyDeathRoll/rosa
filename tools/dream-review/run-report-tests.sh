#!/usr/bin/env bash
# Run the Dream codebase-reviewer's shipped red->green tests against THIS repo,
# with the interpreter they actually need.
#   ./run-report-tests.sh                      # latest rosa report
#   ./run-report-tests.sh 2026-08-13           # a specific report date
#   ./run-report-tests.sh --suite              # ...and the committed pipeline suite
#   ./run-report-tests.sh test_leading_day_dropped.py test_run_skill_override.py
#                                              # only these files (see EXIT below)
#
# Why this exists: the report's tests `import rosa_pipeline`, whose deps live in
# pipeline/.venv - the bare `python3` on PATH has no astral and dies at collection
# with ModuleNotFoundError. Dream's own review-apply.sh runs them with that bare
# interpreter, so every rosa test reports FAIL and its "confirm green" step cries
# wolf on a tree that is green. Run them through here instead, then read
# review-apply.sh's own test output as advisory only.
#
# EXIT: 1 if any test file selected here fails. A finding you DECLINED stays red
# by construction - that is the expected state, not a regression - so scope the
# run to the tests for what you applied by naming those files.
#
# Leaves nothing behind in Dream: no .pyc, no .pytest_cache (the report tree is
# an append-only record, not a scratch dir).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DREAM_ROOT="${DREAM_ROOT:-$HOME/Projects/Dream}"
REPORTS="$DREAM_ROOT/assignments/codebase-reviewer/reports"

PY="$ROOT/pipeline/.venv/bin/python"
export PYTHONPATH="$ROOT/pipeline/src"
export PYTHONDONTWRITEBYTECODE=1

SUITE=0
DATE=""
FILES=()
for a in "$@"; do
  case "$a" in
    --suite)                 SUITE=1 ;;
    -h|--help)               sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    [0-9][0-9][0-9][0-9]-*)  DATE="$a" ;;
    *)                       FILES+=("$a") ;;
  esac
done

[ -x "$PY" ] || { echo "no interpreter at $PY - run \`uv sync\` in pipeline/ first"; exit 1; }
[ -d "$REPORTS" ] || { echo "no reports dir at $REPORTS (set DREAM_ROOT)"; exit 1; }

if [ -z "$DATE" ]; then
  DATE="$(ls -1 "$REPORTS" 2>/dev/null | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort | tail -1)"
fi
RDIR="$REPORTS/$DATE/rosa"
[ -d "$RDIR/tests" ] || { echo "no rosa report tests at $RDIR/tests"; exit 1; }

echo "Report : $RDIR"
echo "Python : PYTHONPATH=pipeline/src $PY"
echo

# ── where each proposed diff stands against the working tree ──────────────────
# Printed, not acted on: it is the context that says whether a red test below is
# a real failure or a finding you chose not to take.
echo "Proposed diffs vs working tree:"
for d in "$RDIR"/*.diff; do
  [ -e "$d" ] || continue
  if   git -C "$ROOT" apply    --check "$d" >/dev/null 2>&1; then s="pending  (tests expected RED)"
  elif git -C "$ROOT" apply -R --check "$d" >/dev/null 2>&1; then s="applied  (tests expected GREEN)"
  else s="CONFLICT (needs --3way or manual)"; fi
  printf "  %-42s %s\n" "$(basename "$d")" "$s"
done
echo

# ── run the shipped tests ─────────────────────────────────────────────────────
if [ "${#FILES[@]}" -eq 0 ]; then
  shopt -s nullglob
  FILES=("$RDIR"/tests/test_*.py)
  shopt -u nullglob
else
  # accept bare basenames as well as paths
  for i in "${!FILES[@]}"; do
    [ -e "${FILES[$i]}" ] || FILES[$i]="$RDIR/tests/${FILES[$i]}"
  done
fi
[ "${#FILES[@]}" -gt 0 ] || { echo "no test_*.py in $RDIR/tests"; exit 1; }

echo "Shipped tests:"
FAIL=0
for t in "${FILES[@]}"; do
  [ -e "$t" ] || { echo "  MISS  $(basename "$t") - no such file"; FAIL=1; continue; }
  out="$(cd "$ROOT" && "$PY" -m pytest -q -p no:cacheprovider "$t" 2>&1)"
  if [ $? -eq 0 ]; then
    echo "  PASS  $(basename "$t")  $(echo "$out" | tail -1)"
  else
    echo "  FAIL  $(basename "$t")"
    echo "$out" | sed 's/^/        /'
    FAIL=1
  fi
done

# ── the committed suite, on request ───────────────────────────────────────────
# The reviewer's own contract is that its diffs leave this green WITHOUT editing
# a committed test, so this is the other half of confirm-green.
if [ "$SUITE" -eq 1 ]; then
  echo
  echo "Committed suite:"
  if out="$(cd "$ROOT" && "$PY" -m pytest -q pipeline/tests 2>&1)"; then
    echo "  PASS  pipeline/tests  $(echo "$out" | tail -1)"
  else
    echo "  FAIL  pipeline/tests"
    echo "$out" | tail -30 | sed 's/^/        /'
    FAIL=1
  fi
fi

# tests that shell out to the CLI can still drop caches in the report tree
rm -rf "$RDIR/tests/__pycache__" "$RDIR/tests/.pytest_cache"

echo
[ "$FAIL" -eq 0 ] && echo "green" || echo "RED - see above (a declined finding's test is red by design)"
exit "$FAIL"
