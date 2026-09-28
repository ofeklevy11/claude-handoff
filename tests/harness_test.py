#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness test: does a REAL Claude Code process load this plugin, run the sentinel hook through the
launcher, and inject the stop message into the model's context? Hooks fire before the model is called,
so this needs no login and costs nothing (the model call itself may fail with an auth error; that is fine).

  python tests/harness_test.py            (CLAUDE_BIN=/path/to/claude to pick a binary)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "handoff"
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
if not CLAUDE:
    sys.exit("claude CLI not found (set CLAUDE_BIN)")
KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
        "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "USERNAME", "LANG"}
base = Path(tempfile.mkdtemp(prefix="handoff-harness-"))
work, state = base / "work", base / "state"
work.mkdir()
state.mkdir()
(state / "usage.json").write_text(json.dumps({"ts": time.time() + 600, "source": "statusline", "five_hour": 84,
                                              "seven_day": 31, "five_hour_resets": "15:10"}), encoding="utf-8")
env = {k: v for k, v in os.environ.items() if k.upper() in KEEP}
env.update({"HANDOFF_STATE_DIR": str(state), "HANDOFF_UNATTENDED": "1"})
subprocess.run([CLAUDE, "-p", "hi", "--model", "haiku", "--plugin-dir", str(PLUGIN), "--setting-sources", "project",
                "--strict-mcp-config", "--max-turns", "1", "--debug-file", str(base / "debug.log")],
               cwd=work, env=env, capture_output=True, timeout=300)
log = (base / "debug.log").read_text(encoding="utf-8", errors="replace") if (base / "debug.log").exists() else ""
states = [json.loads(p.read_text(encoding="utf-8")) for p in (state / "state").glob("*.json")]
fails = 0


def check(name, cond):
    global fails
    fails += not cond
    print(("  ✓ " if cond else "  ✗ ") + name)


check("plugin loaded from --plugin-dir", "Loaded inline plugin from path: handoff" in log)
check("plugin hooks.json read", re.search(r"Read hooks\.json for plugin handoff \(enabled=true\)", log) is not None)
check("skill loaded from the plugin", "Loaded 1 skills from plugin handoff" in log)
check("sentinel ran via the launcher and recorded the session", bool(states) and states[0].get("transcript"))
check("sentinel decided to stop at 84%", bool(states) and "five_hour:act" in (states[0].get("emitted") or {}))
check("harness accepted the output and injected it into context",
      re.search(r"Hook UserPromptSubmit \(sh \"\$\{CLAUDE_PLUGIN_ROOT\}/skills/handoff/scripts/run\.sh\" --sentinel\) "
                r"provided additionalContext", log) is not None)
check("the injected text is the stop message", "עוצרים את העבודה עכשיו" in log)
shutil.rmtree(base, ignore_errors=True)
print(f"\nHARNESS TEST: {'PASS' if not fails else 'FAIL'} ({fails} failed)")
sys.exit(1 if fails else 0)
