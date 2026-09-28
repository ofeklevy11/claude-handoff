#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real install test: `claude plugin marketplace add` + `claude plugin install` into a throwaway
CLAUDE_CONFIG_DIR, exactly as a new user would. Your own ~/.claude is never touched.

  python tests/install_test.py                       # installs from this local checkout
  python tests/install_test.py ofeklevy11/claude-handoff   # installs from GitHub
  CLAUDE_BIN=/path/to/claude python tests/install_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = sys.argv[1] if len(sys.argv) > 1 else str(ROOT)
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
if not CLAUDE:
    sys.exit("claude CLI not found (set CLAUDE_BIN)")

KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
        "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "USERNAME", "LANG"}
cfg = Path(tempfile.mkdtemp(prefix="handoff-install-"))
env = {k: v for k, v in os.environ.items() if k.upper() in KEEP}
env["CLAUDE_CONFIG_DIR"] = str(cfg)
fails = 0


def run(*args):
    r = subprocess.run([CLAUDE, *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    print(f"$ claude {' '.join(args)}\n{(r.stdout + r.stderr).strip()}\n")
    return r


def check(name, cond):
    global fails
    fails += not cond
    print(("  ✓ " if cond else "  ✗ ") + name)


r1 = run("plugin", "marketplace", "add", SOURCE)
r2 = run("plugin", "install", "handoff@claude-handoff")
r3 = run("plugin", "list")
check("marketplace add succeeded", r1.returncode == 0)
check("plugin install succeeded", r2.returncode == 0)
check("plugin listed as installed", "handoff" in r3.stdout)
installed = json.loads((cfg / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
entries = installed.get("plugins", {}).get("handoff@claude-handoff") or []
check("installed_plugins.json has handoff@claude-handoff", bool(entries))
root = Path(entries[0]["installPath"]) if entries else Path("/nonexistent")
for rel in ["skills/handoff/SKILL.md", "skills/handoff/TEMPLATE.md", "skills/handoff/scripts/run.sh",
            "skills/handoff/scripts/handoff.py", "skills/handoff/scripts/sentinel.py", "hooks/hooks.json"]:
    check(f"installed file: {rel}", (root / rel).is_file())
run_sh = root / "skills/handoff/scripts/run.sh"
check("run.sh arrived with LF endings (sh would fail on CRLF)", run_sh.is_file() and b"\r" not in run_sh.read_bytes())
if run_sh.is_file():
    probe = subprocess.run([shutil.which("sh") or "sh", str(run_sh), "--help"], capture_output=True, text=True,
                           encoding="utf-8", env={**env, "HANDOFF_STATE_DIR": str(cfg / "handoff")}, timeout=60)
    check("installed launcher runs (finds Python, prints help)", probe.returncode == 0 and "collect" in probe.stdout)
settings = json.loads((cfg / "settings.json").read_text(encoding="utf-8")) if (cfg / "settings.json").is_file() else {}
check("enabled in settings (no manual edit needed)", settings.get("enabledPlugins", {}).get("handoff@claude-handoff") is True)
check("user hooks untouched (plugin hooks load from the plugin, not settings.json)", "hooks" not in settings)
r4 = run("plugin", "details", "handoff@claude-handoff")
check("details lists the skill and the hooks", r4.returncode == 0 and "handoff" in r4.stdout)
shutil.rmtree(cfg, ignore_errors=True)
print(f"\nINSTALL TEST ({SOURCE}): {'PASS' if not fails else 'FAIL'} ({fails} failed)")
sys.exit(1 if fails else 0)
