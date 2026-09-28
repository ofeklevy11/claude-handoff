#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handoff sentinel — UserPromptSubmit + PostToolUse hook. Silent unless a limit is near.

Where the numbers come from, best first:
  1. usage.json written by statusline_tee.py (terminal, fresh <= 3 min)  -> decides alone.
  2. usage.json written by `handoff.py note` (the model's own get_usage reading, fresh <= 5 min).
  3. Desktop app with no fresh reading -> every N minutes asks the model for a silent get_usage probe.
Never blocks, never fails loudly: any error -> exit 0 with no output.
"""
import json
import os
import sys
import time
from pathlib import Path

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
STATE = Path(os.environ.get("HANDOFF_STATE_DIR") or CLAUDE / "handoff")
USAGE_FILE = STATE / "usage.json"
RUN = (Path(__file__).resolve().parent / "run.sh").as_posix()

DEFAULTS = {
    "five_hour": {"warn": 70, "act": 80},
    "seven_day": {"warn": 85, "act": 93},
    "context": {"warn": 85, "act": None},
    "probe_minutes": 15,
    "probe_minutes_hot": 5,
    "hot_from": 60,
    "first_probe_after_minutes": 5,
    "act_repeat_minutes": 10,
    "fresh_statusline_s": 180,
    "fresh_note_s": 300,
}
LABEL = {"five_hour": "חלון 5 השעות", "seven_day": "המכסה השבועית", "context": "הקונטקסט של הסשן"}


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


DRILL = {"five_hour": {"warn": 1, "act": 1}, "first_probe_after_minutes": 1, "probe_minutes": 1,
         "probe_minutes_hot": 1}


def settings(now=None, sid=None):
    cfg = dict(DEFAULTS)
    layers = [load(STATE / "config.json", {}) or {}]
    drill = load(STATE / "drill.json", {}) or {}
    if drill.get("until", 0) > (now or time.time()) and sid and drill.get("session") == sid:
        # `handoff.py drill on`: this session only stops after a minute of work, whatever the real usage
        layers.append(DRILL)
        cfg["drill_since"] = drill.get("since", 0)
    for layer in layers:
        for k, v in layer.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            elif k in cfg:
                cfg[k] = v
    cfg["drill"] = len(layers) > 1
    return cfg


def level(value, th):
    if value is None:
        return None
    if th.get("act") is not None and value >= th["act"]:
        return "act"
    if th.get("warn") is not None and value >= th["warn"]:
        return "warn"
    return None


def decide(event, sid, now, cfg, st, usage, desktop, terminal=False):
    """Returns the message to inject (or None) and mutates st."""
    emitted = st.setdefault("emitted", {})
    first = st.setdefault("first_seen", now)
    if cfg.get("drill") and now - max(first, cfg.get("drill_since", 0)) < 60:
        return None  # drill: let a minute of real work happen (since the drill began) before the stop
    fresh = None
    if usage:
        age = now - usage.get("ts", 0)
        if usage.get("source") == "statusline" and age <= cfg["fresh_statusline_s"]:
            fresh = usage
        elif usage.get("source") == "get_usage" and age <= cfg["fresh_note_s"]:
            fresh = usage

    if fresh:
        readings = {"five_hour": fresh.get("five_hour"), "seven_day": fresh.get("seven_day")}
        if fresh.get("source") == "statusline" and fresh.get("session_id") == sid:
            readings["context"] = fresh.get("context")
        worst = None
        for metric, value in readings.items():
            lv = level(value, cfg[metric])
            if lv and (worst is None or (lv == "act" and worst[1] != "act")):
                worst = (metric, lv, value)
        if worst:
            metric, lv, value = worst
            reset = f" (מתאפס {fresh['five_hour_resets']})" if metric == "five_hour" and fresh.get("five_hour_resets") else ""
            label = LABEL[metric]
            if st.get("handoff_done"):
                if metric == "five_hour" and value >= 95 and not emitted.get("final"):
                    emitted["final"] = now
                    return (f"[handoff-sentinel] {label} ב-{value:.0f}%{reset}. כבר יש HANDOFF מהסשן הזה "
                            f"({st.get('handoff_folder', '?')}). אם התקדמת מאז, עדכן בו את סעיפים 2, 3, 4 "
                            f"והרץ שוב finalize, עכשיו, לפני שהחלון נסגר.")
                return None
            if lv == "act":
                last = emitted.get(f"{metric}:act", 0)
                if now - last >= cfg["act_repeat_minutes"] * 60:
                    emitted[f"{metric}:act"] = now
                    return (f"⚠️ [handoff-sentinel] {label} ב-{value:.0f}%{reset}. עוצרים את העבודה עכשיו: "
                            f"סיים רק את הפעולה האטומית שבאמצע, אל תתחיל שום צעד חדש במשימה, והפעל מיד את "
                            f"הסקיל handoff. פקודת האיסוף, בדיוק כמו שהיא: "
                            f"`sh \"{RUN}\" collect --reason \"{label} {value:.0f}%\"` "
                            f"ואחרי מילוי HANDOFF.md ו-finalize שעובר את השער, תן למשתמש את הפרומפט")
                return None
            if lv == "warn" and not emitted.get(f"{metric}:warn"):
                emitted[f"{metric}:warn"] = now
                nxt = cfg[metric].get("act")
                tail = f" ב-{nxt}% מפעילים handoff." if nxt else " שקול handoff או סיום נקי של השלב לפני דחיסה."
                return (f"[handoff-sentinel] {label} ב-{value:.0f}%{reset}. עוד לא עוצרים, אבל לא פותחים "
                        f"עכשיו משימה ארוכה בלי נקודת שמירה.{tail} לא צריך להזכיר את זה למשתמש אלא אם זה "
                        f"משנה את התכנית.")
        return None

    # drill with no numbers at all (terminal without the bridge): stop anyway, that is the point of a drill
    if cfg.get("drill") and not desktop and not st.get("handoff_done") and not emitted.get("drill:act"):
        emitted["drill:act"] = now
        return (f"⚠️ [handoff-sentinel] חלון 5 השעות בסף. עוצרים את העבודה עכשיו: סיים רק את הפעולה "
                f"האטומית שבאמצע, אל תתחיל שום צעד חדש במשימה, והפעל מיד את הסקיל handoff. פקודת האיסוף, "
                f"בדיוק כמו שהיא: `sh \"{RUN}\" collect --reason \"תרגיל\"` ואחרי מילוי HANDOFF.md ו-finalize "
                f"שעובר את השער, תן למשתמש את הפרומפט")

    # terminal without the statusline bridge: say so once, ever
    if terminal and event == "UserPromptSubmit" and not (usage or {}).get("source") == "statusline":
        flag = STATE / "terminal-hint-shown"
        if not flag.exists():
            try:
                STATE.mkdir(parents=True, exist_ok=True)
                flag.write_text(str(now), encoding="utf-8")
            except Exception:
                return None
            return (f"[handoff-sentinel] (הודעה חד-פעמית) בטרמינל, זיהוי אוטומטי של חלון 5 השעות עובד רק "
                    f"כשמחברים את ה-statusline. בסוף התשובה הבאה, שאל את המשתמש במשפט אחד אם להפעיל. אם "
                    f"כן: `sh \"{RUN}\" statusline on` (התצוגה שלו לא משתנה, ו-off מחזיר). אם לא, אל תזכיר "
                    f"שוב")
        return None

    # desktop app, no fresh numbers -> periodic silent probe through get_usage
    if not desktop or st.get("handoff_done"):
        return None
    if now - first < cfg["first_probe_after_minutes"] * 60:
        return None
    hot = usage and usage.get("source") == "get_usage" and (usage.get("five_hour") or 0) >= cfg["hot_from"] \
        and now - usage.get("ts", 0) < 45 * 60
    interval = (cfg["probe_minutes_hot"] if hot else cfg["probe_minutes"]) * 60
    if now - st.get("last_probe", 0) < interval:
        return None
    st["last_probe"] = now
    return (f"[handoff-sentinel] בדיקת מכסה שקטה: קרא את mcp__ccd_session_mgmt__get_usage (לא טעון? "
            f"ToolSearch \"select:mcp__ccd_session_mgmt__get_usage\"). "
            f"5 שעות ≥{cfg['five_hour']['act']}% או שבועי ≥{cfg['seven_day']['act']}% → עוצרים את העבודה: "
            f"סיים רק את הפעולה שבאמצע והפעל את הסקיל handoff, ובאיסוף העבר את הקריאה: "
            f"`sh \"{RUN}\" collect --reason \"...\" --five N --week N --resets HH:MM` ; "
            f"5 שעות ≥{cfg['hot_from']}% → רשום את הקריאה: `sh \"{RUN}\" note --five N --week N --resets HH:MM` "
            f"(מקצר את הבדיקה הבאה). אחרת: המשך בשקט, בלי להזכיר את הבדיקה למשתמש")


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        inp = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    if inp.get("agent_id"):
        return  # subagents never hand off; their parent session does
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0" and os.environ.get("HANDOFF_UNATTENDED") != "1":
        return  # scheduled / headless automations stay untouched unless explicitly opted in
    sid = inp.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return
    event = inp.get("hook_event_name") or "UserPromptSubmit"
    now = time.time()
    cfg = settings(now, sid)
    sp = STATE / "state" / f"{sid}.json"
    st = load(sp, {}) or {}
    if inp.get("transcript_path"):
        st["transcript"] = inp["transcript_path"]
    if inp.get("cwd"):
        st["cwd"] = inp["cwd"]
    entry = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")
    desktop = entry == "claude-desktop" or os.environ.get("HANDOFF_FORCE_DESKTOP") == "1"
    terminal = entry == "cli"
    msg = decide(event, sid, now, cfg, st, load(USAGE_FILE), desktop, terminal)
    st["last_seen"] = now
    save(sp, st)
    if msg and cfg.get("drill"):
        msg = "[תרגיל handoff: הסף הורד זמנית ל-1% כדי להדגים. מתנהגים בדיוק כמו באמת] " + msg
    if msg:
        out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}}
        sys.stdout.write(json.dumps(out, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
