#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""statusline tee — caches the plan limits Claude Code hands every statusline call
(rate_limits.five_hour / seven_day, context_window.used_percentage) into usage.json for the
sentinel, then runs the statusline you had before with the same input and prints its output.
Your statusline looks exactly as before; this only listens.

  statusline_tee.py --off   undo the bridge without the plugin (e.g. after uninstalling it): puts your
                            original statusLine back into settings.json exactly, then deletes this file."""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
STATE = Path(os.environ.get("HANDOFF_STATE_DIR") or CLAUDE / "handoff")


def hhmm(epoch):
    try:
        return datetime.fromtimestamp(float(epoch)).astimezone().strftime("%H:%M")
    except Exception:
        return None


def cache(data):
    j = json.loads(data.decode("utf-8", errors="replace"))
    rl = j.get("rate_limits") or {}
    five, week = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    u = {
        "ts": time.time(), "source": "statusline", "session_id": j.get("session_id"),
        "five_hour": five.get("used_percentage"), "five_hour_resets": hhmm(five.get("resets_at")),
        "seven_day": week.get("used_percentage"),
        "context": (j.get("context_window") or {}).get("used_percentage"),
    }
    if all(u[k] is None for k in ("five_hour", "seven_day", "context")):
        return
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = STATE / "usage.tmp"
    tmp.write_text(json.dumps(u, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE / "usage.json")


def bash():
    """On Windows Claude Code runs statusLine commands through Git Bash, so the original must run there too
    (cmd.exe would break `~/...`, `$(...)`, `input=$(cat)`). Same lookup Claude Code uses; never WSL's bash."""
    if os.name != "nt":
        return None
    p = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if p and Path(p).is_file():
        return p
    git = shutil.which("git")
    if git:
        cand = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if cand.is_file():
            return str(cand)
    b = shutil.which("bash")
    return b if b and "system32" not in b.lower() else None


def off():
    """The bridge's `off`, standalone: strict JSON only, exact restore, atomic write, then remove itself."""
    sp = CLAUDE / "settings.json"
    try:
        s = json.loads(sp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        print(f"settings.json missing or not valid JSON ({sp}): not touching it.")
        return 1
    if not isinstance(s, dict):
        print(f"settings.json is not a JSON object ({sp}): not touching it.")
        return 1
    try:
        cfg = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if "statusline_tee.py" in ((s.get("statusLine") or {}).get("command") or ""):
        if "statusline_original" in cfg:
            orig = cfg["statusline_original"]
        elif cfg.get("statusline_passthrough"):
            orig = {**s["statusLine"], "type": "command", "command": cfg["statusline_passthrough"]}
        else:
            orig = None
        if orig:
            s["statusLine"] = orig
        else:
            s.pop("statusLine", None)
        tmp = sp.with_name(sp.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, sp)
    if cfg:
        for k in ("statusline_original", "statusline_passthrough"):
            cfg.pop(k, None)
        (STATE / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        Path(__file__).resolve().unlink()
    except OSError:
        pass
    print("handoff statusline bridge: OFF (original statusline restored, bridge removed)")
    return 0


def main():
    if sys.argv[1:] == ["--off"]:
        sys.exit(off())
    data = sys.stdin.buffer.read()
    try:
        cache(data)
    except Exception:
        pass
    try:
        cfg = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
        orig = cfg.get("statusline_passthrough")
    except Exception:
        orig = None
    if orig:
        try:
            b = bash()
            r = subprocess.run([b, "-c", orig] if b else orig, input=data, capture_output=True, shell=not b, timeout=8)
            sys.stdout.buffer.write(r.stdout)
        except Exception:
            pass


if __name__ == "__main__":
    main()
