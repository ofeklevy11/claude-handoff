#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline test suite for the handoff plugin. No Claude, no network, no cost. Run: python tests/run_tests.py

Covers: plugin/marketplace manifests, secret redaction, every sentinel decision, the hook as a real
process through the sh launcher, the statusline tee, the terminal bridge on/off, and the full
collect -> fill -> finalize pipeline on a synthetic session, plus a gate that must FAIL on each break.
Everything runs inside a throwaway CLAUDE_CONFIG_DIR; your real ~/.claude is never touched."""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "handoff"
SCRIPTS = PLUGIN / "skills" / "handoff" / "scripts"
TMP = Path(tempfile.mkdtemp(prefix="handoff-tests-"))
os.environ.update({"CLAUDE_CONFIG_DIR": str(TMP / "claude"), "HANDOFF_STATE_DIR": str(TMP / "state"),
                   "HANDOFF_OUT_DIR": str(TMP / "out")})
for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ATTENDED", "HANDOFF_FORCE_DESKTOP"):
    os.environ.pop(k, None)
sys.path.insert(0, str(SCRIPTS))
import handoff as h  # noqa: E402
import sentinel as s  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    fails += not cond
    print(("  ✓ " if cond else "  ✗ ") + name)


def section(title):
    print("\n" + title)


# ------------------------------------------------------------------ manifests
section("plugin + marketplace manifests")
mk = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
pl = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
hk = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
check("marketplace: name + owner.name + plugins[]", mk.get("name") and mk.get("owner", {}).get("name") and mk.get("plugins"))
entry = mk["plugins"][0]
check("marketplace source points at the plugin dir", (ROOT / entry["source"]).resolve() == PLUGIN.resolve())
check("plugin name matches marketplace entry", pl.get("name") == entry.get("name") == "handoff")
check("versions agree (marketplace / plugin)", pl.get("version") == entry.get("version") == mk["metadata"]["version"])
skill_md = (PLUGIN / "skills" / "handoff" / "SKILL.md").read_text(encoding="utf-8")
fm = re.match(r"^---\n(.*?)\n---\n", skill_md, re.S)
check("SKILL.md has frontmatter with name + description", fm and "name: handoff" in fm.group(1) and "description:" in fm.group(1))
cmds = [hh["command"] for ev in hk["hooks"].values() for g in ev for hh in g["hooks"]]
check("hooks: UserPromptSubmit + PostToolUse(*)", set(hk["hooks"]) == {"UserPromptSubmit", "PostToolUse"}
      and hk["hooks"]["PostToolUse"][0].get("matcher") == "*")
check("every hook path exists inside the plugin", all(
    (PLUGIN / re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"]+)", c).group(1)).is_file() for c in cmds))
for f in ("handoff.py", "sentinel.py", "statusline_tee.py", "run.sh"):
    check(f"scripts/{f} ships", (SCRIPTS / f).is_file())
check("TEMPLATE.md ships with all 11 sections", all(f"## {i}." in (SCRIPTS.parent / "TEMPLATE.md").read_text(encoding="utf-8") for i in range(12)))

# ------------------------------------------------------------------ secrets
section("secret redaction")
SECRETS = [
    # all fake, built at runtime so no scanner ever mistakes this file for a leak
    'META_ACCESS_TOKEN="EAA' + "FakeTokenForTests" + "0123456789" * 4 + '"',
    "OPENROUTER_KEY: sk-or-v1-" + "0f" * 24,
    "SOME_SERVICE_TOKEN=" + "fa" * 16,
    '{"api_key": "abcd1234efgh5678ijkl"}',
    "postgresql://postgres:hunter2pass@localhost:5434/db",
    "curl 'https://graph.facebook.com/v21.0/act_1/campaigns?access_token=EAAxyz1234567890abcdefghijk&fields=id'",
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
    "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "sk-ant-api03-" + "x" * 40,
    "AKIA" + "ABCDEFGHIJKLMNOP",
]
CODE = [
    "const tokens = JSON.parse(fs.readFileSync(path.join(dir, 'tokens.json'), 'utf8'))",
    "  tokens: DesignTokens;",
    "SORT_KEY=id",
    "password: z.string().min(8)",
    "--token-radius: 12px;",
]
for t in SECRETS:
    r = h.redact(t, count=False)
    check(f"redacts  {t[:46]}", bool(h.find_secrets(t)) and not h.find_secrets(r) and "REDACTED" in r)
for t in CODE:
    check(f"leaves   {t[:46]}", not h.find_secrets(t) and h.redact(t, count=False) == t)

# ------------------------------------------------------------------ sentinel decisions
section("sentinel decisions")
cfg = s.settings()
now = time.time()
sid = "test-session"


def run(usage, st=None, desktop=False, event="PostToolUse", terminal=False):
    st = st if st is not None else {}
    return s.decide(event, sid, now, cfg, st, usage, desktop, terminal), st


def u(src, five=None, week=None, ctx=None, age=0, session=sid):
    return {"ts": now - age, "source": src, "five_hour": five, "seven_day": week, "context": ctx,
            "session_id": session, "five_hour_resets": "15:09"}


STOP = "עוצרים את העבודה עכשיו"
m, _ = run(u("statusline", 40, 10))
check("40% -> silent", m is None)
m, st = run(u("statusline", 72, 10))
check("72% -> warn once", m and "עוד לא עוצרים" in m)
m, _ = run(u("statusline", 74, 10), st)
check("74% again -> no repeated warn", m is None)
m, st = run(u("statusline", 83, 10))
check("83% -> STOP + handoff, with reset time and the exact collect command",
      m and STOP in m and "handoff" in m and "15:09" in m and "run.sh" in m and "collect" in m)
cmd = re.search(r"`([^`]+)`", m or "")
check("stop message: the collect command sits alone in backticks (copyable exactly)",
      cmd and cmd.group(1).startswith("sh ") and cmd.group(1).endswith('%"') and " . " not in (m or ""))
m, _ = run(u("statusline", 84, 10), st)
check("stop not repeated within 10 min", m is None)
st["emitted"]["five_hour:act"] = now - 11 * 60
m, _ = run(u("statusline", 86, 10), st)
check("stop repeats after 10 min if still no handoff", m and STOP in m)
m, _ = run(u("statusline", 50, 94))
check("weekly 94% -> stop", m and "המכסה השבועית" in m and STOP in m)
m, _ = run(u("statusline", 50, 10, ctx=88))
check("context 88% (this session) -> warn only", m and "הקונטקסט" in m and STOP not in m)
m, _ = run(u("statusline", 50, 10, ctx=88, session="other"))
check("context of another session -> ignored", m is None)
m, _ = run(u("statusline", 90, 10, age=600))
check("stale reading -> ignored", m is None)
m, _ = run(u("statusline", 90, 10), {"handoff_done": now})
check("handoff already done at 90% -> silent", m is None)
m, _ = run(u("statusline", 96, 10), {"handoff_done": now, "handoff_folder": "X"})
check("handoff done, 96% -> one 'update it' nudge", m and "finalize" in m)
m, _ = run(None, {"first_seen": now - 60}, desktop=True)
check("desktop, first minutes -> no probe yet", m is None)
m, st = run(None, {"first_seen": now - 6 * 60}, desktop=True)
check("desktop, 6 min in -> silent get_usage probe", m and "get_usage" in m)
m, _ = run(None, st, desktop=True)
check("probe not repeated within interval", m is None)
m, _ = run(u("get_usage", 65, 10, age=6 * 60), {"first_seen": now - 3600, "last_probe": now - 6 * 60}, desktop=True)
check("hot (65% noted) -> probe every 5 min", m and "get_usage" in m)
m, _ = run(u("get_usage", 30, 10, age=6 * 60), {"first_seen": now - 3600, "last_probe": now - 6 * 60}, desktop=True)
check("cool (30% noted) -> waits the full 15 min", m is None)
m, _ = run(u("get_usage", 82, 10, age=60), {"first_seen": now - 3600}, desktop=True)
check("fresh noted 82% -> stop without another probe", m and STOP in m)
m, _ = run(None, {}, terminal=True, event="UserPromptSubmit")
check("terminal without bridge -> one-time hint", m and "statusline on" in m)
m, _ = run(None, {}, terminal=True, event="UserPromptSubmit")
check("terminal hint never repeats", m is None)
m, _ = run(None, {}, terminal=False, event="UserPromptSubmit")
check("headless/SDK -> no hint, no probe", m is None)

section("drill mode")
Path(os.environ["HANDOFF_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
drill_file = Path(os.environ["HANDOFF_STATE_DIR"]) / "drill.json"
drill_file.write_text(json.dumps({"until": now + 600}), encoding="utf-8")
dcfg = s.settings(now)
check("drill on -> threshold 1%, probes every minute", dcfg["drill"] and dcfg["five_hour"]["act"] == 1
      and dcfg["probe_minutes"] == 1)
check("drill: silent during the first minute of work",
      s.decide("PostToolUse", sid, now, dcfg, {"first_seen": now - 20}, u("statusline", 25, 5), False) is None)
m = s.decide("PostToolUse", sid, now, dcfg, {"first_seen": now - 70}, u("statusline", 25, 5), False)
check("drill: after a minute, a real 25% reading -> stop", m and STOP in m)
m = s.decide("PostToolUse", sid, now, dcfg, {"first_seen": now - 70}, None, True)
check("drill (desktop): after a minute -> get_usage probe with 1% threshold", m and "get_usage" in m and "≥1%" in m)
dst = {"first_seen": now - 70}
m = s.decide("PostToolUse", sid, now, dcfg, dst, None, False)
check("drill (no numbers at all): stop anyway", m and STOP in m)
check("drill (no numbers): stop said once", s.decide("PostToolUse", sid, now, dcfg, dst, None, False) is None)
check("expired drill -> normal thresholds", not s.settings(now + 601)["drill"] and s.settings(now + 601)["five_hour"]["act"] == 80)
drill_file.unlink()

# ------------------------------------------------------------------ hook as a real process
section("hook as a real process (sh run.sh --sentinel)")
sh = shutil.which("sh")
check("sh available (Git Bash on Windows)", sh is not None)


def cli(*args):
    return subprocess.run([sh, str(SCRIPTS / "run.sh"), *args], capture_output=True, text=True,
                          encoding="utf-8", env=os.environ, timeout=60)


def hook(payload, extra_env=None):
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run([sh, str(SCRIPTS / "run.sh"), "--sentinel"], input=payload, env=env,
                          capture_output=True, timeout=30)


state = Path(os.environ["HANDOFF_STATE_DIR"])
state.mkdir(parents=True, exist_ok=True)
(state / "usage.json").write_text(json.dumps(u("statusline", 85, 20)), encoding="utf-8")
inp = json.dumps({"session_id": "proc-1", "hook_event_name": "PostToolUse", "transcript_path": "t.jsonl", "cwd": "."})
t0 = time.time()
r = hook(inp.encode())
out = json.loads(r.stdout or b"{}")
ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
check("exit 0 + valid hook JSON + stop message", r.returncode == 0 and STOP in ctx
      and out["hookSpecificOutput"]["hookEventName"] == "PostToolUse")
check("python choice cached for the next call", (state / "python-path").is_file())
r2 = hook(json.dumps({"session_id": "proc-2", "hook_event_name": "PostToolUse"}).encode())
check(f"cached launch is quick ({time.time() - t0:.2f}s for 2 calls)", r2.returncode == 0)
check("state file records transcript + cwd", json.loads((state / "state" / "proc-1.json").read_text(encoding="utf-8"))
      .get("transcript") == "t.jsonl")
r = hook(b"not json")
check("garbage input -> exit 0, no output", r.returncode == 0 and not r.stdout)
r = hook(json.dumps({"session_id": "proc-3", "hook_event_name": "PostToolUse", "agent_id": "sub1"}).encode())
check("subagent tool call -> never hands off", r.returncode == 0 and not r.stdout)
(state / "usage.json").unlink()
bad = tempfile.mkdtemp()
r = subprocess.run([sh, str(SCRIPTS / "run.sh"), "--sentinel"], input=inp.encode(), capture_output=True, timeout=30,
                   env={**os.environ, "PATH": bad, "HANDOFF_STATE_DIR": str(TMP / "nopy")})
check("no Python on the machine -> hook exits 0 silently", r.returncode == 0 and not r.stdout)

# ------------------------------------------------------------------ statusline tee + terminal bridge
section("statusline tee + terminal bridge")
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, "config.json").write_text(json.dumps({"statusline_passthrough": f'"{sys.executable}" -c "print(123)"'}),
                                        encoding="utf-8")
    payload = {"session_id": sid, "rate_limits": {"five_hour": {"used_percentage": 42.5, "resets_at": now + 3600},
                                                 "seven_day": {"used_percentage": 12}},
               "context_window": {"used_percentage": 30}}
    r = subprocess.run([sys.executable, str(SCRIPTS / "statusline_tee.py")], input=json.dumps(payload).encode(),
                       env={**os.environ, "HANDOFF_STATE_DIR": tmp}, capture_output=True, timeout=20)
    cached = json.loads(Path(tmp, "usage.json").read_text(encoding="utf-8"))
    check("tee caches 5h / weekly / context", cached["five_hour"] == 42.5 and cached["seven_day"] == 12 and cached["context"] == 30)
    check("tee passes the original statusline output through", r.stdout.strip() == b"123")

cfgdir = Path(os.environ["CLAUDE_CONFIG_DIR"])
cfgdir.mkdir(parents=True, exist_ok=True)
ORIG = 'powershell -ExecutionPolicy Bypass -File "C:\\x\\my-statusline.ps1"'
(cfgdir / "settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": ORIG},
                                                  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}},
                                                 indent=2), encoding="utf-8")


cli("statusline", "on")
st_on = json.loads((cfgdir / "settings.json").read_text(encoding="utf-8"))
check("bridge on: statusline -> stable tee copy", "statusline_tee.py" in st_on["statusLine"]["command"]
      and (state / "statusline_tee.py").is_file())
check("bridge on: other settings untouched", st_on["hooks"]["Stop"][0]["hooks"][0]["command"] == "x")
cli("statusline", "on")
check("bridge on twice: original kept for pass-through",
      json.loads((state / "config.json").read_text(encoding="utf-8"))["statusline_passthrough"] == ORIG)
check("bridge status reports ON", "ON" in cli("statusline", "status").stdout)
cli("statusline", "off")
check("bridge off: original statusline restored",
      json.loads((cfgdir / "settings.json").read_text(encoding="utf-8"))["statusLine"]["command"] == ORIG)
check("settings backed up before each change", any((cfgdir / "backups").glob("settings.before-handoff-statusline.*.json")))

# ------------------------------------------------------------------ full pipeline on a synthetic session
section("full pipeline: collect -> fill -> finalize -> gate")
work = TMP / "scratch-workspaces" / "demo-work"
(work / "src").mkdir(parents=True)
(work / "src" / "app.js").write_text("const tokens = load('tokens.json')\n", encoding="utf-8")
(work / ".env").write_text("API_KEY=should-never-be-copied-123456\n", encoding="utf-8")
proj = cfgdir / "projects" / "demo"
proj.mkdir(parents=True)
tr = proj / "11111111-2222-3333-4444-555555555555.jsonl"
T = "2026-09-28T09:{:02d}:00.000Z"
lines = [
    {"type": "custom-title", "customTitle": "Demo landing page"},
    {"type": "user", "timestamp": T.format(1), "cwd": str(work), "message": {"content":
        "<system-reminder>noise</system-reminder>בנה לי דף נחיתה לגינון עירוני, 3 סקשנים, בעברית"}},
    {"type": "assistant", "timestamp": T.format(2), "cwd": str(work), "message": {"model": "claude-test", "content": [
        {"type": "text", "text": "מתחיל. https://example.com/docs"},
        {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": str(work / "src" / "app.js"), "content": "x"}},
        {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' x", "description": "call api"}},
        {"type": "tool_use", "id": "t3", "name": "Artifact", "input": {}},
        {"type": "tool_use", "id": "t4", "name": "Skill", "input": {"skill": "frontend-design"}}]}},
    {"type": "user", "timestamp": T.format(3), "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t3", "content": "type_url: https://claude.ai/artifact/TYPECATALOG1 · Published https://claude.ai/artifact/REALPAGE123"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "401 unauthorized", "is_error": True}]}},
    {"type": "attachment", "timestamp": T.format(4), "attachment": {"type": "queued_command",
        "prompt": "<agent-message from=\"x\">subagent report, not the user</agent-message>"}},
    {"type": "user", "timestamp": T.format(5), "message": {"content": "תוסיף גם טופס יצירת קשר"}},
    {"type": "assistant", "timestamp": T.format(6), "message": {"model": "claude-test", "content": [
        {"type": "text", "text": "הטופס בעבודה, נשאר לחבר את הכפתור."}]}},
]
tr.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
(state / "usage.json").write_text(json.dumps(u("statusline", 84, 30)), encoding="utf-8")
r = subprocess.run([sh, str(SCRIPTS / "run.sh"), "collect", "--session", str(tr), "--reason", "5 שעות 84%"],
                   capture_output=True, text=True, encoding="utf-8", env=os.environ, timeout=120)
folder = Path(r.stdout.splitlines()[0].strip()) if r.returncode == 0 and r.stdout else None
check("collect succeeds and prints the folder", folder is not None and (folder / "HANDOFF.md").is_file())
if folder:
    msgs = (folder / "context" / "user-messages.md").read_text(encoding="utf-8")
    check("user messages: both real ones, verbatim, no reminders", "גינון עירוני" in msgs and "טופס יצירת קשר" in msgs
          and "noise" not in msgs)
    check("subagent report is NOT counted as a user message", "subagent report" not in msgs)
    m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    check("artifact kept, type catalog dropped", [a["url"] for a in m["artifacts"]] == ["https://claude.ai/artifact/REALPAGE123"])
    check("skills captured", m["skills"] == ["frontend-design"])
    check("usage at handoff recorded", (m["usage_at_handoff"] or {}).get("five_hour") == 84)
    cmdmd = (folder / "context" / "commands.md").read_text(encoding="utf-8")
    check("bearer token in a command -> redacted", "REDACTED" in cmdmd and "abcdefghijklmnopqrstuvwxyz123456" not in cmdmd)
    check("scratch workspace copied, .env skipped", (folder / "workspace" / "src" / "app.js").is_file()
          and not (folder / "workspace" / ".env").exists())
    check("workspace code copied verbatim (not 'redacted' into breakage)",
          (folder / "workspace" / "src" / "app.js").read_text(encoding="utf-8") == "const tokens = load('tokens.json')\n")
    md = (folder / "HANDOFF.md").read_text(encoding="utf-8")
    check("skeleton has 10 <<FILL>> blocks", md.count("<<FILL") == 10)
    rc = subprocess.run([sh, str(SCRIPTS / "run.sh"), "finalize", str(folder)], capture_output=True, text=True,
                        encoding="utf-8", env=os.environ, timeout=120)
    check("finalize refuses while <<FILL>> remain", rc.returncode != 0)
    FILLS = {
        0: "1. דף נחיתה לגינון עירוני בעברית, 3 סקשנים.\n2. שלד הדף קיים, טופס יצירת קשר באמצע.\n3. לחבר את כפתור השליחה.",
        1: "המשתמש ביקש \"בנה לי דף נחיתה לגינון עירוני, 3 סקשנים, בעברית\" ואחר כך הוסיף טופס יצירת קשר.",
        2: f"- `{work / 'src' / 'app.js'}` קיים (אומת ב-09:10).",
        3: "באמצע טופס יצירת הקשר: השדות קיימים, הכפתור עוד לא מחובר.",
        4: "1. לחבר את כפתור השליחה ב-`src/app.js`.\n2. 🔒 לשאול את המשתמש לאן נשלחים הטפסים.",
        5: "- עברית בלבד, כי המשתמש ביקש.",
        6: "- קצר ולעניין.",
        7: "- קריאת ה-API החזירה 401. המפתח לא תקף, יושב ב-`.env`.",
        9: f"1. `ls \"{work}\"`. צפוי: src/.\n2. לפתוח את `src/app.js`. צפוי: שורת tokens.",
    }
    filled = md
    for num, text in FILLS.items():
        filled = re.sub(r"(## %d\.[^\n]*\n)<<FILL:[^\n]*>>" % num, lambda mm, t=text: mm.group(1) + t, filled)
    filled = re.sub(r"(## 10\.[^\n]*\n)<<FILL:[^\n]*>>", r"\1אין.", filled)
    (folder / "HANDOFF.md").write_text(filled, encoding="utf-8")
    cli("drill", "on", "--minutes", "5")
    check("drill on via CLI", (state / "drill.json").is_file())
    rc = subprocess.run([sh, str(SCRIPTS / "run.sh"), "finalize", str(folder)], capture_output=True, text=True,
                        encoding="utf-8", env=os.environ, timeout=180)
    check("finalize -> GATE: PASS", rc.returncode == 0 and "GATE: PASS" in rc.stdout)
    check("a finalized handoff ends the drill by itself", not (state / "drill.json").exists() and "DRILL" in rc.stdout)
    check("PROMPT.txt + PROMPT-FULL.md + zip + INDEX + LATEST", all(p.exists() for p in [
        folder / "PROMPT.txt", folder / "PROMPT-FULL.md", folder.parent / f"{folder.name}.zip",
        folder.parent / "INDEX.md", folder.parent / "LATEST.txt"]))
    check("PROMPT.txt points to the folder and to the workspace copy",
          str(folder) in (folder / "PROMPT.txt").read_text(encoding="utf-8")
          and "workspace" in (folder / "PROMPT.txt").read_text(encoding="utf-8"))
    sst = json.loads((state / "state" / f"{tr.stem}.json").read_text(encoding="utf-8"))
    check("sentinel told the handoff is done (stops alerting this session)", sst.get("handoff_done"))

    def gate(mutate):
        d = TMP / f"gate-{time.time_ns()}"
        shutil.copytree(folder, d, ignore=shutil.ignore_patterns("workspace"))
        (d / "workspace").mkdir()
        (d / "workspace" / "x").write_text("x", encoding="utf-8")
        (d / "PROMPT.txt").write_text((d / "PROMPT.txt").read_text(encoding="utf-8").replace(str(folder), str(d)),
                                      encoding="utf-8")
        (d / "HANDOFF.md").write_text(mutate((d / "HANDOFF.md").read_text(encoding="utf-8")), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            return h.cmd_verify(argparse.Namespace(folder=str(d)))

    check("gate: clean copy passes", gate(lambda x: x) == 0)
    check("gate: open <<FILL>> fails", gate(lambda x: x.replace("הכפתור עוד", "<<FILL: x>> הכפתור עוד")) != 0)
    check("gate: leaked secret fails", gate(lambda x: x.replace("אין ידועות", "sk-proj-" + "Ab3" * 14).replace(
        "- קריאת ה-API", "- sk-proj-" + "Ab3" * 14 + " קריאת ה-API")) != 0)
    check("gate: next steps without numbers fails", gate(lambda x: x.replace("1. לחבר", "- לחבר").replace("2. 🔒", "- 🔒")) != 0)
    check("gate: empty core section fails", gate(lambda x: re.sub(r"(## 3\.[^\n]*\n)[^\n]+", r"\1", x)) != 0)

section("latest / find / status")
r = cli("latest")
check("latest -> newest folder", folder and str(folder) in r.stdout)
r = cli("find", "Demo landing")
check("find by session title -> uuid", tr.stem in r.stdout)
check("status runs", cli("status").returncode == 0)
check("a trailing '.' copied with a command is tolerated", cli("status", ".").returncode == 0)
check("a real unknown argument is still rejected", cli("status", "--bogus").returncode != 0)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nTESTS: {'PASS' if not fails else 'FAIL'} ({fails} failed)")
sys.exit(1 if fails else 0)
