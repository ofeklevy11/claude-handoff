#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end: a REAL headless Claude Code session, with this plugin loaded, works on a multi-step task
while plan usage climbs past the limit. Pass = it stops mid-task, runs the handoff skill, and the
handoff folder passes the gate. Uses your Claude login and costs tokens (one short Sonnet session per
scenario). Your settings, hooks and plugins are NOT loaded (--setting-sources project, --strict-mcp-config).

  python tests/e2e.py                 # both scenarios, in parallel
  python tests/e2e.py terminal        # statusline path: usage.json climbs 55% -> 84% after the first file
  python tests/e2e.py desktop         # desktop path: get_usage probes return 35%, then 86%
  CLAUDE_BIN=... E2E_MODEL=sonnet E2E_KEEP=1 python tests/e2e.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "handoff"
SCRIPTS = PLUGIN / "skills" / "handoff" / "scripts"
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
MODEL = os.environ.get("E2E_MODEL", "sonnet")
KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
        "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "USERNAME", "LANG"}
TASK_FILES = ["01-intro.md", "02-soil.md", "03-plants.md", "04-water.md", "05-tools.md", "06-summary.md"]
PROMPT = ("בתיקייה הזו כתוב מדריך קצר לגינון עירוני בעברית: שישה קבצי Markdown, כל קובץ בקריאת Write נפרדת, "
          "בסדר הזה: " + ", ".join(TASK_FILES) + ". כל קובץ 5 עד 8 שורות. אחרי כל קובץ המשך מיד לקובץ הבא, "
          "בלי לשאול אותי כלום.")


def usage_file(state, five, week=31):
    tmp = state / "usage.tmp"
    tmp.write_text(json.dumps({"ts": time.time(), "source": "statusline", "session_id": None, "five_hour": five,
                               "five_hour_resets": time.strftime("%H:%M", time.localtime(time.time() + 2820)),
                               "seven_day": week, "context": None}), encoding="utf-8")
    os.replace(tmp, state / "usage.json")


def scenario(name):
    base = Path(tempfile.mkdtemp(prefix=f"handoff-e2e-{name}-"))
    work, state, out = base / "work", base / "state", base / "out"
    for d in (work, state, out):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP}
    # -p runs count as unattended; the sentinel leaves those alone unless explicitly opted in
    env.update({"HANDOFF_STATE_DIR": str(state), "HANDOFF_OUT_DIR": str(out), "HANDOFF_UNATTENDED": "1"})
    args = [CLAUDE, "-p", PROMPT, "--model", MODEL, "--plugin-dir", str(PLUGIN), "--setting-sources", "project",
            "--output-format", "stream-json", "--verbose", "--max-turns", "80", "--strict-mcp-config",
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Write,Read,Edit,Bash,Glob,Grep,Skill,ToolSearch,mcp__ccd_session_mgmt__get_usage"]
    stop_climb = threading.Event()
    if name == "desktop":
        env["HANDOFF_FORCE_DESKTOP"] = "1"
        (state / "config.json").write_text(json.dumps({"first_probe_after_minutes": 0, "probe_minutes": 0.25,
                                                       "probe_minutes_hot": 0.25}), encoding="utf-8")
        mcp = {"mcpServers": {"ccd_session_mgmt": {"command": sys.executable, "args": [str(ROOT / "tests" / "fake_usage_mcp.py")],
                                                  "env": {"FAKE_USAGE_COUNTER": str(state / "fake-calls"),
                                                          "FAKE_USAGE_SEQUENCE": "35,86"}}}}
        (base / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
        args += ["--mcp-config", str(base / "mcp.json")]
    else:
        usage_file(state, 55)

        def climb():  # the statusline keeps refreshing; usage jumps once real work has started
            high = False
            while not stop_climb.is_set():
                high = high or any((work / f).exists() for f in TASK_FILES)
                usage_file(state, 84 if high else 55)
                stop_climb.wait(1)
        threading.Thread(target=climb, daemon=True).start()

    t0 = time.time()
    with open(base / "stream.jsonl", "w", encoding="utf-8") as fh:
        proc = subprocess.run(args, cwd=work, env=env, stdout=fh, stderr=subprocess.PIPE, text=True,
                              encoding="utf-8", timeout=1800)
    stop_climb.set()
    return base, proc, time.time() - t0


def verdict(name, base, proc, secs):
    work, state, out = base / "work", base / "state", base / "out"
    events = []
    for line in (base / "stream.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except Exception:
            pass
    calls = []
    for e in events:
        if e.get("type") == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use":
                    calls.append((b.get("name"), b.get("input") or {}))
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    names = [c[0] for c in calls]
    skill_i = next((i for i, (n, inp) in enumerate(calls) if n == "Skill" and "handoff" in str(inp.get("skill", ""))), None)
    collect_i = next((i for i, (n, inp) in enumerate(calls) if n == "Bash" and "collect" in inp.get("command", "")), None)
    first_stop = skill_i if skill_i is not None else collect_i
    task_writes_after = [c for c in calls[(first_stop or 10 ** 9) + 1:]
                         if c[0] == "Write" and Path(c[1].get("file_path", "")).name in TASK_FILES]
    made = [f for f in TASK_FILES if (work / f).exists()]
    folders = [p for p in out.iterdir() if p.is_dir()] if out.exists() else []
    st = {}
    for sp in (state / "state").glob("*.json"):
        st = json.loads(sp.read_text(encoding="utf-8"))
    gate = subprocess.run([sys.executable, str(SCRIPTS / "handoff.py"), "verify", str(folders[0])],
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "HANDOFF_STATE_DIR": str(state)}) if folders else None
    checks = [
        ("session finished", proc.returncode == 0 and result.get("subtype") == "success"),
        ("sentinel fired the stop signal", any(k.endswith(":act") for k in (st.get("emitted") or {}))),
        ("real work started before the stop (≥1 task file)", len(made) >= 1),
        ("work stopped: not all 6 task files were written", len(made) < len(TASK_FILES)),
        ("nothing skipped: the files written are the first N, in order", made == TASK_FILES[:len(made)]),
        ("handoff skill invoked (or its collect ran)", first_stop is not None),
        ("no task writes after the stop", not task_writes_after),
        ("handoff folder created", bool(folders)),
        ("handoff passes the gate (independent re-verify)", gate is not None and gate.returncode == 0),
        ("PROMPT.txt ready", bool(folders) and (folders[0] / "PROMPT.txt").is_file()),
    ]
    if name == "desktop":
        n = int((state / "fake-calls").read_text()) if (state / "fake-calls").exists() else 0
        checks.insert(2, ("desktop: model probed get_usage at least twice (35% then 86%)", n >= 2))
    ok = all(c for _, c in checks)
    print(f"\n=== e2e:{name} · {secs / 60:.1f} min · {len(calls)} tool calls · cost ${result.get('total_cost_usd', 0):.2f}")
    print("    tools in order:", " → ".join(names[:60]) + (" …" if len(names) > 60 else ""))
    print(f"    task files written: {made}")
    for label, c in checks:
        print(("    ✓ " if c else "    ✗ ") + label)
    if gate is not None:
        print("    gate:", gate.stdout.strip().splitlines()[-1])
    print(f"    artifacts kept in: {base}" if os.environ.get("E2E_KEEP") or not ok else "")
    if proc.stderr.strip():
        print("    stderr:", proc.stderr.strip()[-600:])
    final = (result.get("result") or "")[-900:]
    print("    final message (tail):\n      " + final.replace("\n", "\n      "))
    return ok, base


def main():
    if not CLAUDE:
        sys.exit("claude CLI not found (set CLAUDE_BIN)")
    which = sys.argv[1:] or ["terminal", "desktop"]
    results = {}

    def go(n):
        results[n] = scenario(n)
    threads = [threading.Thread(target=go, args=(n,)) for n in which]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    all_ok = True
    for n in which:
        ok, base = verdict(n, *results[n])
        all_ok &= ok
        if ok and not os.environ.get("E2E_KEEP"):
            shutil.rmtree(base, ignore_errors=True)
    print(f"\nE2E: {'PASS' if all_ok else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
