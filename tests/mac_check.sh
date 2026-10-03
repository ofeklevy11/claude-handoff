#!/bin/sh
# macOS checks that need a real Mac (CI: .github/workflows/mac-e2e.yml). No Claude login, no cost.
#   sh tests/mac_check.sh gui     an app opened from the Dock: PATH=/usr/bin:/bin:/usr/sbin:/sbin
#   sh tests/mac_check.sh noclt   the same, on a Mac with no developer tools (Xcode and CLT removed first)
#   OLD_RUN=/path/run.sh (1.0.5 launcher, next to its sentinel.py): run it too, as a control
mode=${1:-gui}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUN="$ROOT/skills/handoff/scripts/run.sh"
GUI_PATH=/usr/bin:/bin:/usr/sbin:/sbin
fail=0
ok() { echo "  ✓ $1"; }
bad() { echo "  ✗ $1"; fail=1; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

echo "macOS $(sw_vers -productVersion) $(uname -m) · mode: $mode"
[ "$(uname -s)" = Darwin ] || { echo "not a Mac"; exit 2; }

hook() {  # $1 launcher, $2 state dir, $3 session -> stdout of the hook; the sh -x trace goes to $2/trace
  printf '{"ts": %s, "source": "statusline", "five_hour": 85, "seven_day": 20}' "$(date +%s)" > "$2/usage.json"
  printf '{"session_id":"%s","hook_event_name":"PostToolUse"}' "${3:-mac-1}" |
    env -i HOME="$HOME" PATH="$GUI_PATH" HANDOFF_STATE_DIR="$2" sh -x "$1" --sentinel 2>"$2/trace"
}

if [ "$mode" = noclt ]; then
  check "no developer tools: xcode-select -p fails" '! /usr/bin/xcode-select -p >/dev/null 2>&1'
  # with no developer tools /usr/bin/python3 hands off to a python3 on PATH; on the Dock PATH there is none
  check "no developer tools: with the Dock PATH, /usr/bin/python3 is only the install stub"     '! env -i HOME="$HOME" PATH="$GUI_PATH" /usr/bin/python3 -c 1 >/dev/null 2>&1'
fi
check "no python3 on the Dock PATH except /usr/bin/python3" \
  '[ "$(PATH=$GUI_PATH command -v python3)" = /usr/bin/python3 ] || [ -z "$(PATH=$GUI_PATH command -v python3)" ]'

st=$(mktemp -d)
out=$(hook "$RUN" "$st")
cached=$(cat "$st/python-path" 2>/dev/null)
echo "    1.0.6 launcher picked: ${cached:-none}"
check "1.0.6: the hook runs with the Dock PATH and injects the stop message" \
  'printf "%s" "$out" | grep -q "hookSpecificOutput" && printf "%s" "$out" | grep -q "handoff-sentinel"'
check "1.0.6: cached a full path" 'case "$cached" in /*) true ;; *) false ;; esac'
if [ "$mode" = noclt ]; then
  check "1.0.6: never ran /usr/bin/python3 (no install popup)" '! grep -Eq "^\++ */usr/bin/python3 -c" "$st/trace"'
  check "1.0.6: used a real Python from an install folder" '[ "$cached" != /usr/bin/python3 ]'
  out2=$(hook "$RUN" "$st" mac-2)  # a new session: the first one was already told to stop
  check "1.0.6: second call (cached) still works and still skips the stub" \
    'printf "%s" "$out2" | grep -q "handoff-sentinel" && ! grep -Eq "^\++ */usr/bin/python3 -c" "$st/trace"'
fi

if [ -n "$OLD_RUN" ]; then
  so=$(mktemp -d)
  old=$(hook "$OLD_RUN" "$so")
  echo "    (control) 1.0.5 tried: $(grep -E '^\++ *[^ ]*python[0-9.]* -c' "$so/trace" | sed 's/ -c.*//; s/^+* *//' | tr '
' ' ')· output: $([ -n "$old" ] && echo stop message || echo nothing)"
  if [ "$mode" = noclt ]; then
    check "control, 1.0.5 on the same Mac: ran the stub (popup) and the hook did nothing" \
      'grep -Eq "^\++ *python3 -c" "$so/trace" && [ -z "$old" ]'
  fi
fi

guard=$("${BREW_PY:-python3}" -c "import sys; sys.path.insert(0, sys.argv[1]); import handoff; print(handoff.macos_stub('/usr/bin/git'))"   "$ROOT/skills/handoff/scripts" 2>&1)
if [ "$mode" = noclt ]; then
  check "collect will not touch the /usr/bin/git stub either (no popup during a handoff)" '[ "$guard" = True ]'
else
  check "with developer tools, collect still uses /usr/bin/git" '[ "$guard" = False ]'
fi

# Desktop that macOS will not let the app write to: collect must fall back to ~/handoffs
H=$(mktemp -d)
mkdir -p "$H/Desktop" "$H/.claude/projects/p" "$H/work"
chmod 500 "$H/Desktop"
printf '%s\n' '{"type":"user","timestamp":"2026-10-03T10:00:00.000Z","cwd":"'"$H/work"'","message":{"content":"hello from a Mac"}}' \
  > "$H/.claude/projects/p/11111111-2222-3333-4444-555555555555.jsonl"
cout=$(cd "$H/work" && env -i HOME="$H" PATH="$GUI_PATH" CLAUDE_CONFIG_DIR="$H/.claude" HANDOFF_STATE_DIR="$st" \
  sh "$RUN" collect --session "$H/.claude/projects/p/11111111-2222-3333-4444-555555555555.jsonl" --reason mac 2>"$H/err")
folder=$(printf '%s\n' "$cout" | head -1)
echo "    collect -> $folder"
check "Desktop not writable: collect falls back to ~/handoffs" \
  'case "$folder" in "$H/handoffs/"*) [ -f "$folder/HANDOFF.md" ] ;; *) false ;; esac'
check "... and says so" 'grep -q "note: cannot write to" "$H/err"'
chmod 700 "$H/Desktop"

echo "MAC CHECK ($mode): $([ $fail = 0 ] && echo PASS || echo FAIL)"
exit $fail
