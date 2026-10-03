#!/bin/sh
# Launcher for the handoff scripts: finds a Python 3.8+ once, caches its full path, then execs the script with the
# same stdin/args.
#   sh run.sh <handoff.py args>      the handoff CLI (the skill uses this)
#   sh run.sh --sentinel             the hook; with no Python it exits 0 silently instead of erroring
# Where it looks: $HANDOFF_PYTHON, then python3 / python / py on PATH, then the usual install dirs. Those matter on
# macOS: an app opened from the Dock gets PATH=/usr/bin:/bin:/usr/sbin:/sbin, without Homebrew or python.org Python.
# dirname understands Windows paths (C:\x\run.sh); on a bare PATH without it, a shell built-in does the job
here=$(dirname -- "$0" 2>/dev/null) || { here=${0%/*}; [ "$here" = "$0" ] && here=.; }
script=handoff.py
hook=
if [ "$1" = "--sentinel" ]; then script=sentinel.py; hook=1; shift; fi

state="${HANDOFF_STATE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/handoff}"
cache="$state/python-path"
os="${HANDOFF_TEST_OS:-$(uname -s 2>/dev/null || /usr/bin/uname -s 2>/dev/null)}"
stub="${HANDOFF_TEST_STUB:-/usr/bin/python3}"

# Without the Command Line Tools, macOS /usr/bin/python3 is a stub that opens an "install developer tools" dialog
# each time it runs. It is only run when xcode-select says the tools are installed.
usable() {
  if [ "$os" = Darwin ] && [ "$1" = "$stub" ]; then
    [ -z "$HANDOFF_TEST_STUB" ] && /usr/bin/xcode-select -p >/dev/null 2>&1 || return 1
  fi
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 8))' </dev/null >/dev/null 2>&1
}

py=
if [ -f "$cache" ]; then
  IFS= read -r py < "$cache" 2>/dev/null
  case "$py" in
    /*) [ -x "$py" ] || py= ;;
    *) py= ;;  # 1.0.5 cached a bare name, which on macOS can resolve to the developer-tools stub
  esac
  if [ -n "$py" ] && [ "$os" = Darwin ] && [ "$py" = "$stub" ] && ! usable "$py"; then py=; fi
fi
if [ -z "$py" ]; then
  for c in "$HANDOFF_PYTHON" python3 python py \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/local/bin/python3 \
           "$HOME/.pyenv/shims/python3" "$HOME/.local/bin/python3" "$HOME/miniconda3/bin/python3" \
           "$HOME/anaconda3/bin/python3" "$HOME/miniforge3/bin/python3" \
           /home/linuxbrew/.linuxbrew/bin/python3 /usr/bin/python3 /bin/python3; do
    [ -n "$c" ] || continue
    case "$c" in
      /*) [ -x "$c" ] && [ ! -d "$c" ] && p=$c || continue ;;
      *) p=$(command -v "$c" 2>/dev/null) || continue ;;
    esac
    if usable "$p"; then
      py=$p
      mkdir -p "$state" 2>/dev/null && printf '%s' "$p" > "$cache" 2>/dev/null
      break
    fi
  done
fi
if [ -z "$py" ]; then
  [ -n "$hook" ] && exit 0
  echo "handoff: Python 3.8+ not found (tried \$HANDOFF_PYTHON, python3, python, py and the usual install folders)." >&2
  if [ "$os" = Darwin ]; then
    echo "handoff: on macOS run 'xcode-select --install' or 'brew install python', or set HANDOFF_PYTHON=/path/to/python3." >&2
  else
    echo "handoff: install Python 3 (e.g. 'sudo apt install python3'), or set HANDOFF_PYTHON=/path/to/python3." >&2
  fi
  exit 127
fi
exec "$py" "$here/$script" "$@"
