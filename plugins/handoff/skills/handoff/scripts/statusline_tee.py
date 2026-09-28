#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""statusline tee — caches the plan limits Claude Code hands every statusline call
(rate_limits.five_hour / seven_day, context_window.used_percentage) into usage.json for the
sentinel, then runs the statusline you had before with the same input and prints its output.
Your statusline looks exactly as before; this only listens."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

STATE = Path(os.environ.get("HANDOFF_STATE_DIR")
             or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "handoff")


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


def main():
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
            r = subprocess.run(orig, input=data, capture_output=True, shell=True, timeout=8)
            sys.stdout.buffer.write(r.stdout)
        except Exception:
            pass


if __name__ == "__main__":
    main()
