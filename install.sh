#!/bin/sh
# claude-handoff one-line install (macOS / Linux / Git Bash):
#   curl -fsSL https://raw.githubusercontent.com/ofeklevy11/claude-handoff/v1.0.5/install.sh | sh
# Same as typing in Claude Code:  /plugin marketplace add ofeklevy11/claude-handoff
#                                 /plugin install handoff@claude-handoff
set -e
if ! command -v claude >/dev/null 2>&1; then
  echo "claude-handoff: Claude Code CLI not found. Install it first: https://claude.com/claude-code" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1 && ! command -v py >/dev/null 2>&1; then
  echo "claude-handoff: warning: Python 3.8+ not found. The plugin installs, but needs Python to run." >&2
fi
claude plugin marketplace add ofeklevy11/claude-handoff || claude plugin marketplace update claude-handoff
claude plugin install handoff@claude-handoff
echo
echo "claude-handoff installed. Open a NEW Claude Code session and it is active."
