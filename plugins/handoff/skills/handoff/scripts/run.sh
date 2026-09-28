#!/bin/sh
# Launcher for the handoff scripts: finds a Python 3.8+ once (python3, python or the Windows py
# launcher), caches the choice, then execs the script with the same stdin/args.
#   sh run.sh <handoff.py args>      the handoff CLI (the skill uses this)
#   sh run.sh --sentinel             the hook; with no Python it exits 0 silently instead of erroring
here=$(dirname -- "$0")
script=handoff.py
hook=
if [ "$1" = "--sentinel" ]; then script=sentinel.py; hook=1; shift; fi

state="${HANDOFF_STATE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/handoff}"
cache="$state/python-path"
py=
if [ -f "$cache" ]; then
  py=$(cat "$cache" 2>/dev/null)
  command -v "$py" >/dev/null 2>&1 || py=
fi
if [ -z "$py" ]; then
  for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' </dev/null >/dev/null 2>&1; then
      py=$c
      mkdir -p "$state" 2>/dev/null && printf '%s' "$c" > "$cache" 2>/dev/null
      break
    fi
  done
fi
if [ -z "$py" ]; then
  [ -n "$hook" ] && exit 0
  echo "handoff: Python 3.8+ not found (tried python3, python, py). Install Python and try again." >&2
  exit 127
fi
exec "$py" "$here/$script" "$@"
