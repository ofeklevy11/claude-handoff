#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness test: does a REAL Claude Code process load this plugin, run the sentinel hook through the
launcher, and inject its message into the model's context? Hooks fire before the model is called, so
this needs no login and costs nothing (the model call itself may then fail with an auth error; fine).

  python tests/harness_test.py              # the plugin from this checkout (--plugin-dir)
  python tests/harness_test.py --installed  # YOUR installed plugin, with your own settings
  CLAUDE_BIN=/path/to/claude python tests/harness_test.py

Two scenarios: terminal (a fresh statusline reading of 84% -> stop) and desktop app (no reading yet ->
silent get_usage probe). Your real handoff state is never touched (a throwaway HANDOFF_STATE_DIR)."""
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
PLUGIN = ROOT  # 1.0.6: the repo root is the plugin, so the ZIP GitHub makes of it uploads as is
INSTALLED = "--installed" in sys.argv
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
if not CLAUDE:
    sys.exit("claude CLI not found (set CLAUDE_BIN)")
KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
        "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "USERNAME", "LANG"}
fails = 0


def check(name, cond):
    global fails
    fails += not cond
    print(("  ✓ " if cond else "  ✗ ") + name)


def session(desktop):
    base = Path(tempfile.mkdtemp(prefix="handoff-harness-"))
    work, state = base / "work", base / "state"
    work.mkdir()
    state.mkdir()
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP}
    env.update({"HANDOFF_STATE_DIR": str(state), "HANDOFF_UNATTENDED": "1"})
    if desktop:
        env["HANDOFF_FORCE_DESKTOP"] = "1"
        (state / "config.json").write_text(json.dumps({"first_probe_after_minutes": 0}), encoding="utf-8")
    else:
        (state / "usage.json").write_text(json.dumps({"ts": time.time() + 600, "source": "statusline", "five_hour": 84,
                                                      "seven_day": 31, "five_hour_resets": "15:10"}), encoding="utf-8")
    args = [CLAUDE, "-p", "hi", "--model", "haiku", "--strict-mcp-config", "--max-turns", "1",
            "--debug-file", str(base / "debug.log")]
    args += ["--setting-sources", "user"] if INSTALLED else ["--plugin-dir", str(PLUGIN), "--setting-sources", "project"]
    subprocess.run(args, cwd=work, env=env, capture_output=True, timeout=300)
    log = (base / "debug.log").read_text(encoding="utf-8", errors="replace") if (base / "debug.log").exists() else ""
    states = [json.loads(p.read_text(encoding="utf-8")) for p in (state / "state").glob("*.json")]
    shutil.rmtree(base, ignore_errors=True)
    return log, states


injected = re.compile(r"Hook UserPromptSubmit \(sh \"\$\{CLAUDE_PLUGIN_ROOT\}/skills/handoff/scripts/run\.sh\" "
                      r"--sentinel\) provided additionalContext")
where = "your installed plugin" if INSTALLED else "this checkout"
print(f"terminal scenario ({where})")
log, states = session(desktop=False)
if INSTALLED:
    check("installed plugin's hooks.json read from the plugin cache",
          re.search(r"Read hooks\.json for plugin handoff \(enabled=true\): .*plugins[\\/]cache[\\/]claude-handoff", log) is not None)
else:
    check("plugin loaded from --plugin-dir", "Loaded inline plugin from path: handoff" in log)
check("skill loaded from the plugin", "Loaded 1 skills from plugin handoff" in log)
check("sentinel ran via the launcher and recorded the session", bool(states) and states[0].get("transcript"))
check("sentinel decided to stop at 84%", bool(states) and "five_hour:act" in (states[0].get("emitted") or {}))
check("harness injected the message into the model's context", injected.search(log) is not None)
check("the injected text is the stop message", "עוצרים את העבודה עכשיו" in log)

print(f"\ndesktop-app scenario ({where})")
log, states = session(desktop=True)
check("harness injected the probe into the model's context", injected.search(log) is not None)
check("the probe asks for get_usage with the 80% rule", "get_usage" in log and "≥80%" in log)
check("probe time recorded (next one in 15 min)", bool(states) and states[0].get("last_probe"))

print(f"\nHARNESS TEST ({where}): {'PASS' if not fails else 'FAIL'} ({fails} failed)")
sys.exit(1 if fails else 0)
