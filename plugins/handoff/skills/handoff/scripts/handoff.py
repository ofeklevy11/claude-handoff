#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handoff — pack a Claude Code session so a fresh session (or another account) continues it.

  collect   [--session self|<uuid>|<file.jsonl>] [--name N] [--reason R] [--cwd DIR] [--copy-workspace]
            builds <out>/<date>_<slug>/ : HANDOFF.md skeleton + context/ + memory/ (+ workspace/)
  finalize  <folder> [--no-zip]   PROMPT.txt + PROMPT-FULL.md + INDEX + zip, then runs the gate
  verify    <folder>              the gate alone (exit 1 on FAIL)
  note      --five N [--week N] [--resets HH:MM]   record a get_usage reading for the sentinel
  find      <title text>          session uuid by its (desktop) title, for handing off another session
  status                          usage cache + sentinel state for this session
  latest                          newest handoff folder
  statusline on|off|status        terminal only: bridge the statusline's rate_limits to the sentinel
                                  (your statusline keeps looking exactly the same; off restores it)
  drill on [--minutes 30] | off   rehearsal: threshold 1% so the next session stops after a minute and
                                  hands off for real; switches itself off once that handoff is finalized
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path.home()
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")
PROJECTS = CLAUDE / "projects"
SKILL_DIR = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get("HANDOFF_STATE_DIR") or CLAUDE / "handoff")
USAGE_FILE = STATE / "usage.json"
CONFIG_FILE = STATE / "config.json"
DEFAULT_OUT = (HOME / "Desktop" if (HOME / "Desktop").is_dir() else HOME) / "handoffs"

FILL = "<<FILL"
REQUIRED_SECTIONS = ["## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.",
                     "## 7.", "## 8.", "## 9.", "## 10."]
MUST_HAVE_BODY = ["## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 9."]
TEXT_EXT = {".md", ".txt", ".json", ".jsonl", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py",
            ".html", ".htm", ".css", ".yml", ".yaml", ".toml", ".ini", ".env", ".sh", ".ps1",
            ".csv", ".xml", ".svg", ".sql", ".cfg", ".conf"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".next", ".cache", ".turbo"}
SECRET_FILES = re.compile(r"(^\.env(\..*)?$|\.pem$|\.key$|\.p12$|\.pfx$|credentials.*\.json$|"
                          r"secrets?\.(json|ya?ml|toml)$|^id_(rsa|ed25519))", re.I)
MAX_FILE_COPY = 60 * 1024 * 1024
MAX_WORKSPACE = 500 * 1024 * 1024
LONG = "\\\\?\\"

# ---------------------------------------------------------------- secrets
_SECRET_RULES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"), None),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), None),
    ("openrouter-key", re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"), None),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}"), None),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"), None),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), None),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"), None),
    ("meta-token", re.compile(r"\bEAA[A-Za-z0-9]{40,}"), None),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), None),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"), None),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), None),
    ("bearer", re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._\-]{20,})"), 2),
    ("url-secret", re.compile(r"(?i)([?&](?:access_token|token|key|api_key|apikey|secret|password|pwd)=)([^&\s\"'<>]{8,})"), 2),
    ("conn-string", re.compile(r"(?i)\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/@]+:)([^@\s]+)(@)"), 2),
    ("env-secret", re.compile(r"\b([A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|_KEY)[A-Z0-9_]*\s*[=:]\s*[\"']?)([A-Za-z0-9_\-./+=]{12,})"), 2),
    ("quoted-secret", re.compile(r"(?i)([\"'](?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|client[_-]?secret|secret[_-]?key|password)[\"']\s*[:=]\s*[\"'])([^\"'\s]{12,})([\"'])"), 2),
]
REDACTIONS = Counter()


def redact(text, count=True):
    if not text:
        return text
    for name, rx, grp in _SECRET_RULES:
        def _sub(m, name=name, grp=grp):
            if count:
                REDACTIONS[name] += 1
            if grp is None:
                return f"[REDACTED:{name}]"
            return "".join(f"[REDACTED:{name}]" if i == grp else (m.group(i) or "")
                           for i in range(1, (m.lastindex or 0) + 1))
        text = rx.sub(_sub, text)
    return text


def find_secrets(text):
    hits = []
    for name, rx, grp in _SECRET_RULES:
        for m in rx.finditer(text):
            val = m.group(grp) if grp else m.group(0)
            if val and not val.startswith("[REDACTED"):
                hits.append(name)
    return hits

# ---------------------------------------------------------------- helpers


def now_local():
    return datetime.now().astimezone()


def to_local(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone() if ts else None
    except Exception:
        return None


def fmt(dt, with_date=True):
    return dt.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M") if dt else "?"


def clip(text, n):
    text = text or ""
    return text if len(text) <= n else text[:n].rstrip() + f" …[+{len(text) - n} תווים]"


def slugify(s):
    s = re.sub(r"[^\w֐-׿\- ]", "", s or "").strip()
    s = re.sub(r"[\s_]+", "-", s)
    return (s or "session")[:40].strip("-")


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def load_json(p, default=None):
    try:
        return json.loads(L(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def read(p):
    return L(p).read_text(encoding="utf-8")


def rel(fp, cwd):
    """Path shown relative to the work dir when it lives inside it — tables stay readable."""
    try:
        return str(Path(fp).relative_to(Path(cwd)))
    except Exception:
        return str(fp)


def L(p):
    """Windows long-path form, so deep workspace copies never hit the 260-char limit."""
    s = str(Path(p).resolve())
    if os.name == "nt" and not s.startswith(LONG):
        s = LONG + s
    return Path(s)


def write(p, text):
    p = L(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def config():
    cfg = {"out_dir": os.environ.get("HANDOFF_OUT_DIR") or str(DEFAULT_OUT)}
    cfg.update({k: v for k, v in (load_json(CONFIG_FILE, {}) or {}).items() if k != "out_dir"
                or not os.environ.get("HANDOFF_OUT_DIR")})
    return cfg


def encode_cwd(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def find_transcript(session, cwd):
    if session and session.endswith(".jsonl"):
        p = Path(session).expanduser()
        if p.is_file():
            return p
        sys.exit(f"transcript not found: {session}")
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID") if session in (None, "", "self") else session
    if sid:
        hits = list(PROJECTS.glob(f"*/{sid}.jsonl"))
        if hits:
            return max(hits, key=lambda p: p.stat().st_mtime)
        if session not in (None, "", "self"):
            sys.exit(f"no transcript for session {sid} under {PROJECTS}")
    # the sentinel records every live session's transcript path: newest one for this cwd wins
    here = os.path.normcase(os.path.abspath(str(cwd)))
    live = []
    for sp in (STATE / "state").glob("*.json"):
        st = load_json(sp, {}) or {}
        t = st.get("transcript")
        if t and st.get("cwd") and os.path.normcase(os.path.abspath(st["cwd"])) == here and Path(t).is_file():
            live.append((st.get("last_seen", 0), Path(t)))
    if live:
        return max(live)[1]
    d = PROJECTS / encode_cwd(cwd)
    cands = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    if not cands:
        sys.exit(f"no transcript found for cwd {cwd} (tried {d}); pass --session <uuid|path>")
    return cands[0]

# ---------------------------------------------------------------- transcript parsing


_TAG_BLOCKS = re.compile(r"<(system-reminder|ide_[a-z_]+|local-command-caveat)>[\s\S]*?</\1>")
_CMD = re.compile(r"<command-name>([\s\S]*?)</command-name>[\s\S]*?(?:<command-args>([\s\S]*?)</command-args>)?")
_NOT_HUMAN = ("<task-notification>", "Another Claude session sent a message", "[Subagent hand-back]",
              "<agent-message", "<ci-monitor-event>", "Caveat: The messages below")
_URL = re.compile(r"https?://[^\s)\]>\"'`]+")
_ARTIFACT = re.compile(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9\-]+")


def human_text(o):
    if o.get("type") != "user" or o.get("isMeta") or o.get("isSidechain") or o.get("isCompactSummary"):
        return None
    c = (o.get("message") or {}).get("content")
    if isinstance(c, list):
        blocks = [b for b in c if isinstance(b, dict)]
        if any(b.get("type") == "tool_result" for b in blocks):
            return None
        imgs = sum(1 for b in blocks if b.get("type") == "image")
        c = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        c += "\n[תמונה מצורפת]" * imgs
    if not isinstance(c, str):
        return None
    t = _TAG_BLOCKS.sub("", c)
    m = _CMD.search(t)
    if m:
        t = f"{m.group(1).strip()} {(m.group(2) or '').strip()}".strip()
    t = re.sub(r"<local-command-stdout>[\s\S]*?</local-command-stdout>", "", t).strip()
    if not t or t.startswith(_NOT_HUMAN):
        return None
    return t


def tool_result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return c if isinstance(c, str) else ""


def parse_transcript(path):
    S = {"title": None, "cwd": None, "models": Counter(), "first": None, "last": None, "version": None,
         "prompts": [], "turns": [], "texts": [], "files": OrderedDict(), "commands": [], "skills": [],
         "artifacts": OrderedDict(), "sent": [], "agents": [], "errors": [], "todos": None,
         "compact": [], "context_tokens": None, "urls": Counter(), "entrypoint": None}
    tools = {}
    seen_prompts = set()
    type_urls = set()
    turn = None

    def new_turn(ts, text, queued=False):
        nonlocal turn
        key = re.sub(r"\s+", " ", text)[:500]
        if key in seen_prompts:
            return
        seen_prompts.add(key)
        S["prompts"].append({"ts": ts, "text": text, "queued": queued})
        turn = {"ts": ts, "prompt": text, "tools": Counter(), "files": [], "last_text": ""}
        S["turns"].append(turn)

    def touch(fp, action, ts):
        if not fp:
            return
        p = Path(fp)
        if not p.is_absolute() and S["cwd"]:
            p = Path(S["cwd"]) / p
        k = str(p)
        e = S["files"].pop(k, {"actions": Counter(), "first": ts})
        e["actions"][action] += 1
        e["last"] = ts
        S["files"][k] = e
        if turn is not None and k not in turn["files"]:
            turn["files"].append(k)

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            ts = o.get("timestamp")
            if ts:
                S["first"] = S["first"] or ts
                S["last"] = ts
            if o.get("cwd") and not o.get("isSidechain"):
                S["cwd"] = o["cwd"]
            S["version"] = o.get("version") or S["version"]
            S["entrypoint"] = o.get("entrypoint") or S["entrypoint"]
            if t == "custom-title" and o.get("customTitle"):
                S["title"] = o["customTitle"]
            elif t == "summary" and o.get("summary") and not S["title"]:
                S["title"] = o["summary"]
            elif t == "frame-link" and o.get("frameUrl"):
                S["artifacts"][o["frameUrl"]] = o.get("title") or ""
            elif t == "file-history-delta" and o.get("trackingPath"):
                touch(o["trackingPath"], "tracked", ts)
            elif t == "attachment":
                a = o.get("attachment") or {}
                if a.get("type") == "queued_command" and isinstance(a.get("prompt"), str):
                    txt = human_text({"type": "user", "message": {"content": a["prompt"]}})
                    if txt:
                        new_turn(ts, txt, queued=True)
            elif t == "user":
                if o.get("isCompactSummary"):
                    c = (o.get("message") or {}).get("content")
                    if isinstance(c, list):
                        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict))
                    S["compact"].append({"ts": ts, "text": c or ""})
                    continue
                txt = human_text(o)
                if txt:
                    new_turn(ts, txt)
                    continue
                c = (o.get("message") or {}).get("content")
                if isinstance(c, list) and not o.get("isSidechain"):
                    for b in c:
                        if not isinstance(b, dict) or b.get("type") != "tool_result":
                            continue
                        name, tinp = tools.get(b.get("tool_use_id"), ("?", {}))
                        body = tool_result_text(b)
                        publish = tinp.get("action", "publish") == "publish" and not tinp.get("asset")
                        if name == "Artifact" and publish:  # list/read results are not this session's pages
                            type_urls.update(re.findall(r"type_url[\"':\s]*(" + _ARTIFACT.pattern + ")", body or ""))
                            for u in _ARTIFACT.findall(body or ""):
                                S["artifacts"].setdefault(u, "")
                        if b.get("is_error"):
                            S["errors"].append({"ts": ts, "tool": name, "text": clip(body, 400)})
            elif t == "assistant" and not o.get("isSidechain"):
                msg = o.get("message") or {}
                if msg.get("model") and not msg["model"].startswith("<"):
                    S["models"][msg["model"]] += 1
                u = msg.get("usage") or {}
                if u:
                    S["context_tokens"] = sum(u.get(k) or 0 for k in (
                        "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        S["texts"].append({"ts": ts, "text": b["text"]})
                        for url in _URL.findall(b["text"]):
                            S["urls"][url.rstrip(".,;:*_")] += 1
                        if turn is not None:
                            turn["last_text"] = b["text"]
                    elif b.get("type") == "tool_use":
                        name, inp = b.get("name", "?"), b.get("input") or {}
                        tools[b.get("id")] = (name, inp)
                        if turn is not None:
                            turn["tools"][name] += 1
                        if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                            touch(inp.get("file_path") or inp.get("notebook_path"),
                                  "write" if name == "Write" else "edit", ts)
                        elif name in ("Bash", "PowerShell"):
                            S["commands"].append({"ts": ts, "tool": name, "desc": inp.get("description", ""),
                                                  "cmd": inp.get("command", "")})
                        elif name == "Skill":
                            S["skills"].append({"ts": ts, "skill": inp.get("skill"), "args": inp.get("args", "")})
                        elif name == "SendUserFile":
                            for f in inp.get("files") or []:
                                S["sent"].append({"ts": ts, "file": f, "caption": inp.get("caption", "")})
                                touch(f, "sent", ts)
                        elif name == "Agent":
                            S["agents"].append({"ts": ts, "desc": inp.get("description", ""),
                                                "type": inp.get("subagent_type", "")})
                        elif name == "TodoWrite":
                            S["todos"] = inp.get("todos")
    for u in type_urls:
        if not S["artifacts"].get(u):
            S["artifacts"].pop(u, None)
    return S

# ---------------------------------------------------------------- context files


def md_user_messages(S):
    out = ["# כל מה שהמשתמש כתב בסשן — מילה במילה", "",
           "מקור האמת לבקשות. הודעות שנשלחו בזמן שהסוכן עבד מסומנות \"בתור\".", ""]
    for i, p in enumerate(S["prompts"], 1):
        q = " · בתור" if p["queued"] else ""
        out += [f"## {i}. {fmt(to_local(p['ts']))}{q}", "", redact(clip(p["text"], 6000)), ""]
    return "\n".join(out)


def md_timeline(S):
    out = ["# ציר זמן — תור אחרי תור", "",
           "לכל בקשה: מה נעשה (כלים, קבצים) ומה הייתה התשובה האחרונה של הסוכן באותו תור.", ""]
    for i, t in enumerate(S["turns"], 1):
        tools = ", ".join(f"{k}×{v}" for k, v in t["tools"].most_common(8)) or "—"
        out += [f"## תור {i} · {fmt(to_local(t['ts']))}", "",
                "**בקשה:** " + redact(clip(t["prompt"], 700)), "", f"**כלים:** {tools}"]
        if t["files"]:
            out.append("**קבצים:** " + ", ".join(f"`{rel(f, S['cwd'])}`" for f in t["files"][:12])
                       + (f" (+{len(t['files']) - 12})" if len(t["files"]) > 12 else ""))
        out += ["", "**סוף התור (תשובת הסוכן):**", "", redact(clip(t["last_text"], 1500)) or "—", "", "---", ""]
    return "\n".join(out)


def md_assistant_tail(S, n=30):
    out = ["# הודעות הסוכן האחרונות", ""]
    for x in S["texts"][-n:]:
        out += [f"### {fmt(to_local(x['ts']))}", "", redact(clip(x["text"], 3000)), ""]
    return "\n".join(out)


def md_commands(S, n=60):
    out = ["# פקודות אחרונות שהורצו", "", "| זמן | כלי | תיאור | פקודה |", "|---|---|---|---|"]
    for c in S["commands"][-n:]:
        cmd = redact(clip(c["cmd"].replace("\n", " ⏎ "), 260)).replace("|", "\\|")
        out.append(f"| {fmt(to_local(c['ts']), False)} | {c['tool']} | {c['desc'].replace('|', '/')} | `{cmd}` |")
    return "\n".join(out)


def file_rows(S, limit=None):
    rows = []
    items = list(S["files"].items())[::-1]
    for fp, e in (items[:limit] if limit else items):
        p = L(fp)
        if p.exists():
            st = p.stat()
            state = "תיקייה" if p.is_dir() else human_size(st.st_size)
            mt = fmt(datetime.fromtimestamp(st.st_mtime).astimezone())
        else:
            state, mt = "**לא קיים**", "—"
        acts = Counter(e["actions"])
        if len(acts) > 1:
            acts.pop("tracked", None)
        rows.append((rel(fp, S["cwd"]), ", ".join(f"{k}×{v}" for k, v in acts.most_common()), state, mt))
    return rows


def md_files(S):
    out = ["# קבצים שנגעו בהם בסשן (אחרון למעלה)", "", f"נתיבים יחסיים ל-`{S['cwd']}`.", "",
           "| קובץ | פעולות | גודל עכשיו | שונה לאחרונה |", "|---|---|---|---|"]
    out += [f"| `{fp}` | {acts} | {state} | {mt} |" for fp, acts, state, mt in file_rows(S)]
    return "\n".join(out)


def md_errors(S, n=20):
    out = ["# שגיאות כלים אחרונות", "", "רמזים למלכודות — מה נכשל בדרך.", ""]
    out += [f"- **{fmt(to_local(e['ts']), False)} · {e['tool']}:** {redact(e['text']).replace(chr(10), ' ')}"
            for e in S["errors"][-n:]]
    return "\n".join(out)


def git_info(cwd):
    if not cwd or not Path(cwd).is_dir():
        return None

    def g(*a):
        try:
            r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, timeout=20,
                               encoding="utf-8", errors="replace")
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None
    if g("rev-parse", "--is-inside-work-tree") != "true":
        return None
    lines = (g("status", "--short") or "").splitlines()
    return {
        "root": g("rev-parse", "--show-toplevel"),
        "branch": g("branch", "--show-current") or g("rev-parse", "--short", "HEAD"),
        "status": "\n".join(lines[:80]) + (f"\n… (+{len(lines) - 80})" if len(lines) > 80 else ""),
        "dirty": len(lines),
        "log": g("log", "--oneline", "-12") or "",
        "diffstat": ((g("diff", "--stat") or "").splitlines() or [""])[-1],
        "stash": g("stash", "list") or "",
        "upstream": g("rev-list", "--left-right", "--count", "@{u}...HEAD"),
    }


def md_git(info):
    if not info:
        return "לא ריפו git."
    ahead = ""
    if info["upstream"]:
        behind, ah = (info["upstream"].split() + ["0", "0"])[:2]
        ahead = f" · מול upstream: {ah} קדימה, {behind} מאחור"
    out = [f"- שורש: `{info['root']}` · ענף: `{info['branch']}` · {info['dirty']} קבצים לא מקומטים{ahead}"]
    if info["diffstat"]:
        out.append(f"- diff: {info['diffstat'].strip()}")
    if info["stash"]:
        out.append(f"- stash: {len(info['stash'].splitlines())} רשומות")
    out += ["", "```", "$ git status --short", info["status"] or "(נקי)", "", "$ git log --oneline -12",
            info["log"], "```"]
    return "\n".join(out)

# ---------------------------------------------------------------- copies


def copy_memory(cwd, transcript, dest):
    copied, srcs = [], []
    mem = transcript.parent / "memory"
    if mem.is_dir():
        srcs += [(p, f"auto-memory/{p.name}") for p in sorted(mem.glob("*.md"))]
    if cwd and Path(cwd).is_dir():
        root = Path(cwd)
        for rel in ["CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md", "PROJECT-MEMORY.md", "CHECKBOXES.md",
                    "COUNCIL-LOG.md", "LAUNCH-PLAN.md", "PLAN.md", "STATUS.md", "TODO.md"]:
            if (root / rel).is_file():
                srcs.append((root / rel, f"project/{rel.replace('/', '__')}"))
        for d in ["memory", ".claude/memory", "docs/memory"]:
            if (root / d).is_dir():
                srcs += [(p, f"project/{d.replace('/', '__')}__{p.name}") for p in sorted((root / d).glob("*.md"))]
        srcs += [(p, f"project/{p.name}") for p in sorted(root.glob("*ledger*.md"))]
    for src, rel in srcs:
        try:
            if src.stat().st_size <= 400_000:
                write(dest / rel, redact(src.read_text(encoding="utf-8", errors="replace")))
                copied.append({"from": str(src), "to": f"memory/{rel}"})
        except Exception:
            pass
    return copied


def copy_workspace(cwd, dest):
    rep = {"files": 0, "bytes": 0, "skipped_large": [], "skipped_secret": [], "truncated": False}
    root, dest = L(cwd), L(dest)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            src = Path(dirpath) / fn
            rel = src.relative_to(root)
            if SECRET_FILES.search(fn):
                rep["skipped_secret"].append(str(rel))
                continue
            try:
                size = src.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_COPY:
                rep["skipped_large"].append(f"{rel} ({human_size(size)})")
                continue
            if rep["bytes"] + size > MAX_WORKSPACE:
                rep["truncated"] = True
                return rep
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)  # verbatim: it is a backup of real work, redacting code would break it
            rep["files"] += 1
            rep["bytes"] += size
    return rep

# ---------------------------------------------------------------- usage


def read_usage(max_age=None):
    u = load_json(USAGE_FILE)
    if not u or (max_age and time.time() - u.get("ts", 0) > max_age):
        return None
    return u


def usage_line(u):
    if not u:
        return "לא נמדד (אין קריאה טרייה)"
    parts = []
    if u.get("five_hour") is not None:
        r = u.get("five_hour_resets")
        parts.append(f"5 שעות {u['five_hour']:.0f}%" + (f" (מתאפס {r})" if r else ""))
    if u.get("seven_day") is not None:
        parts.append(f"שבועי {u['seven_day']:.0f}%")
    if u.get("context") is not None:
        parts.append(f"קונטקסט {u['context']:.0f}%")
    age = int((time.time() - u.get("ts", time.time())) / 60)
    return " · ".join(parts) + f" · נמדד לפני {age} דק' ({u.get('source', '?')})"

# ---------------------------------------------------------------- collect


def cmd_collect(a):
    cwd_hint = a.cwd or os.getcwd()
    transcript = find_transcript(a.session, cwd_hint)
    S = parse_transcript(transcript)
    cwd = a.cwd or S["cwd"] or cwd_hint
    sid = transcript.stem
    title = a.name or S["title"] or Path(cwd).name
    stamp = now_local()
    out_root = Path(config()["out_dir"])
    folder = out_root / f"{stamp:%Y-%m-%d_%H%M}_{slugify(title)}"
    n = 2
    while folder.exists():
        folder = out_root / f"{stamp:%Y-%m-%d_%H%M}_{slugify(title)}-{n}"
        n += 1
    ctx = folder / "context"
    L(ctx).mkdir(parents=True)

    is_scratch = "scratch-workspaces" in str(cwd).replace("/", "\\")
    write(ctx / "user-messages.md", md_user_messages(S))
    write(ctx / "timeline.md", md_timeline(S))
    write(ctx / "assistant-tail.md", md_assistant_tail(S))
    write(ctx / "files.md", md_files(S))
    if S["commands"]:
        write(ctx / "commands.md", md_commands(S))
    if S["errors"]:
        write(ctx / "errors.md", md_errors(S))
    if S["compact"]:
        write(ctx / "compact-summary.md", "# סיכום דחיסה אחרון (הסשן נדחס — פרטים מוקדמים חיים רק כאן)\n\n"
              + redact(S["compact"][-1]["text"]))
    urls = [u for u, _ in S["urls"].most_common(60)]
    if urls or S["artifacts"]:
        lines = ["# קישורים", "", "## ארטיפקטים שפורסמו", ""]
        lines += [f"- {t or '(ללא כותרת)'} — {u}" for u, t in S["artifacts"].items()] or ["—"]
        lines += ["", "## קישורים שהסוכן הזכיר (לפי תדירות)", ""] + [f"- {redact(u)}" for u in urls]
        write(ctx / "links.md", "\n".join(lines))
    gi = git_info(cwd)
    if gi:
        write(ctx / "git.md", "# git\n\n" + md_git(gi))
    mem = copy_memory(cwd, transcript, folder / "memory")
    ws = None
    if (is_scratch or a.copy_workspace) and Path(cwd).is_dir():
        ws = copy_workspace(cwd, folder / "workspace")

    usage = read_usage(max_age=30 * 60)
    models = ", ".join(m for m, _ in S["models"].most_common()) or "?"
    skills = list(OrderedDict((s["skill"], None) for s in S["skills"] if s["skill"]))
    workdir_note = ""
    if ws:
        workdir_note = (f"> ⚠️ תיקיית העבודה המקורית זמנית (של האפליקציה) ונמחקת עם הסשן. "
                        f"עותק מלא: `{folder / 'workspace'}` ({ws['files']} קבצים, {human_size(ws['bytes'])}). "
                        f"הסשן החדש עובד מהעותק.")
    rows = file_rows(S, limit=15)
    files_table = "\n".join([f"נתיבים יחסיים לתיקיית העבודה{' (וגם לעותק ב-workspace/)' if ws else ''}.", "",
                             "| קובץ | פעולות | עכשיו |", "|---|---|---|"]
                            + [f"| `{fp}` | {acts} | {state} |" for fp, acts, state, _ in rows]) if rows else "—"
    if len(S["files"]) > 15:
        files_table += f"\n\n…ועוד {len(S['files']) - 15} ב-`context/files.md`"
    arts = "\n".join(f"- {t or '(ללא כותרת)'} — {u}" for u, t in S["artifacts"].items()) or "—"
    if S["sent"]:
        sent = list(OrderedDict((rel(x["file"], cwd), None) for x in S["sent"]))
        arts += "\n\nקבצים שנשלחו למשתמש בסשן: " + ", ".join(f"`{x}`" for x in sent[-12:])
    skills_md = ("\n".join(f"- `{s}`" for s in skills) + "\n\nבסשן החדש: להפעיל אותם (Skill) לפני שממשיכים."
                 ) if skills else "—"
    F = L(folder)
    ctx_files = sorted(p.relative_to(F).as_posix() for d in ("context", "memory") for p in (F / d).rglob("*.md"))
    ctx_index = "\n".join(f"- `{p}`" for p in ctx_files)
    ctx_index += f"\n- תמליל מלא (לחיפוש ממוקד בלבד, לא לקריאה): `{transcript}`"

    tpl = (SKILL_DIR / "TEMPLATE.md").read_text(encoding="utf-8")
    reps = {
        "TITLE": title, "CREATED": fmt(stamp), "REASON": a.reason or "ידני",
        "MODEL": models, "SESSION": f"{S['title'] or '—'} · `{sid}`", "CWD": str(cwd),
        "WORKDIR_NOTE": workdir_note, "USAGE": usage_line(usage),
        "SPAN": f"{fmt(to_local(S['first']))} → {fmt(to_local(S['last']), False)} · "
                f"{len(S['prompts'])} הודעות משתמש · {len(S['turns'])} תורות",
        "FILES_TABLE": files_table, "ARTIFACTS": arts, "SKILLS": skills_md, "GIT": md_git(gi),
        "CONTEXT_INDEX": ctx_index,
    }
    for k, v in reps.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    write(folder / "HANDOFF.md", tpl)

    manifest = {
        "version": 1, "created": stamp.isoformat(timespec="seconds"), "name": title,
        "reason": a.reason or "manual", "session_id": sid, "session_title": S["title"],
        "transcript": str(transcript), "cwd": str(cwd), "is_scratch": is_scratch,
        "work_dir": str(folder / "workspace") if ws else str(cwd),
        "models": list(S["models"]), "claude_code_version": S["version"], "entrypoint": S["entrypoint"],
        "span": [S["first"], S["last"]], "user_messages": len(S["prompts"]), "turns": len(S["turns"]),
        "context_tokens_last": S["context_tokens"], "usage_at_handoff": usage,
        "skills": skills, "artifacts": [{"url": u, "title": t} for u, t in S["artifacts"].items()],
        "files_touched": len(S["files"]), "memory_files": mem, "workspace": ws, "git": bool(gi),
        "redactions": dict(REDACTIONS),
    }
    write(folder / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(folder)
    print(f"  session   : {S['title'] or '—'} ({sid})")
    print(f"  prompts   : {len(S['prompts'])} · turns {len(S['turns'])} · files {len(S['files'])}"
          f" · artifacts {len(S['artifacts'])} · skills {', '.join(skills) or '—'}")
    if ws:
        print(f"  workspace : {ws['files']} files, {human_size(ws['bytes'])}"
              f"{' (TRUNCATED at cap)' if ws['truncated'] else ''}; skipped large {len(ws['skipped_large'])},"
              f" secret-like {len(ws['skipped_secret'])}")
    print(f"  redacted  : {sum(REDACTIONS.values())} secret-like strings")
    print(f'NEXT: fill every <<FILL>> in HANDOFF.md, then: handoff.py finalize "{folder}"')

# ---------------------------------------------------------------- finalize / verify


def section_bodies(md):
    parts = re.split(r"(?m)^(## \d+\..*)$", md)
    out = {}
    for i in range(1, len(parts) - 1, 2):
        out[re.match(r"## \d+\.", parts[i]).group(0)] = parts[i + 1].strip()
    return out


def build_prompts(folder, m, handoff_md):
    work = m.get("work_dir") or m.get("cwd")
    reason = m.get("reason") or "manual"
    short = f"""המשך עבודה מ-HANDOFF: "{m.get('name')}"

סשן קודם נעצר ({reason}) באמצע עבודה. כל ההקשר שמור בתיקייה:
{folder}

לפני כל דבר אחר:
1. קרא במלואו את {folder / 'HANDOFF.md'} — זה מקור האמת.
2. עבוד בתיקייה: {work}
3. הפעל את הסקילים שרשומים בסעיף 8 של ה-HANDOFF (אם יש).
4. הרץ את בדיקות סעיף 9 ("איך לאמת"). משהו לא תואם למתואר? עצור ודווח לפני שנוגעים בקבצים.
5. כתוב לי 3 שורות: מה המשימה, איפה עצרנו, מה הצעד הבא — ואז המשך מיד לצעד 1 בסעיף 4. צעד שמסומן 🔒 מחכה לאישור שלי.

כללים: לא לפתוח מחדש החלטות מסעיף 5. לא לעשות שוב מה שגמור בסעיף 2.
פרט שחסר? context/user-messages.md (כל מה שכתבתי, מילה במילה) ו-context/timeline.md באותה תיקייה.
התמליל המלא ({m.get('transcript')}) — רק לחיפוש ממוקד, לא לקריאה מלאה.
"""
    um = read(folder / "context" / "user-messages.md")
    full = f"""# המשך עבודה מ-HANDOFF — {m.get('name')}

> לסשן בלי גישה לקבצים של המחשב המקורי (claude.ai, מחשב אחר, מנוי אחר על מחשב אחר).
> יש לך גישה לקבצים של המחשב המקורי? השתמש ב-PROMPT.txt במקום.

סשן קודם נעצר ({reason}). כל מה שצריך כדי להמשיך נמצא למטה: מסמך ה-HANDOFF המלא
ואחריו כל ההודעות שכתבתי בסשן, מילה במילה. קבצי העבודה עצמם נמצאים ב-ZIP המצורף
(`{folder.name}.zip`) — לא צורף? בקש אותו לפני שאתה נוגע בקבצים.

מה לעשות:
1. קרא את ה-HANDOFF עד הסוף.
2. כתוב לי 3 שורות: מה המשימה, איפה עצרנו, מה הצעד הבא.
3. המשך מצעד 1 בסעיף 4. צעד 🔒 מחכה לאישור שלי. לא לפתוח מחדש החלטות מסעיף 5.

נתיבים במסמך הם של המחשב המקורי. אחרי חילוץ ה-ZIP, התיקייה `workspace/` (אם קיימת) מחליפה את תיקיית העבודה.

---

{handoff_md}

---

{clip(um, 60000)}
"""
    return short, full


def cmd_verify(a):
    folder = Path(a.folder).expanduser().resolve()
    fails, warns, ok = [], [], []

    def check(cond, msg, level="fail"):
        (ok if cond else (fails if level == "fail" else warns)).append(msg)

    F = L(folder)
    m = load_json(F / "manifest.json", {}) or {}
    for f in ["HANDOFF.md", "manifest.json", "context/user-messages.md", "context/timeline.md",
              "PROMPT.txt", "PROMPT-FULL.md"]:
        check((F / f).is_file(), f"קיים: {f}")
    md = read(F / "HANDOFF.md") if (F / "HANDOFF.md").is_file() else ""
    left = md.count(FILL)
    check(left == 0, f"אין <<FILL>> פתוחים ({left} נשארו)")
    bodies = section_bodies(md)
    for s in REQUIRED_SECTIONS:
        check(s in bodies, f"סעיף קיים: {s}")
    for s in MUST_HAVE_BODY:
        body = re.sub(r"\s+", " ", bodies.get(s, ""))
        check(len(body) >= 40 and FILL not in body, f"סעיף {s} מלא בתוכן אמיתי")
    check(re.search(r"(?m)^\s*1\.\s+\S", bodies.get("## 4.", "")) is not None, "סעיף 4: רשימה ממוספרת של צעדים")
    check(len(md.splitlines()) <= 400, f"HANDOFF.md קריא (≤400 שורות; יש {len(md.splitlines())})", "warn")
    hits, ws_hits = [], []
    for p in F.rglob("*"):
        if p.is_file() and p.suffix.lower() in TEXT_EXT and p.stat().st_size < 8_000_000:
            try:
                found = find_secrets(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            if found:
                r = p.relative_to(F)
                (ws_hits if r.parts[0] == "workspace" else hits).append(f"{r} ({', '.join(sorted(set(found)))})")
    check(not hits, "אין סודות גלויים במסמכים" + (": " + "; ".join(hits[:8]) if hits else ""))
    check(not ws_hits, "עותק ה-workspace נקי מסודות (הוא עותק מדויק, לא מצונזר)"
          + (": " + "; ".join(ws_hits[:8]) if ws_hits else ""), "warn")
    missing = [p for p in set(re.findall(r"`([A-Za-z]:[\\/][^`*?\"<>|\n]+)`", md))
               if not L(p).exists() and "REDACTED" not in p]
    check(not missing, "כל הנתיבים שב-HANDOFF קיימים" + (": " + "; ".join(missing[:6]) if missing else ""), "warn")
    if (F / "PROMPT.txt").is_file():
        check(str(folder) in read(F / "PROMPT.txt"), "PROMPT.txt מצביע לתיקייה הנכונה")
    if m.get("is_scratch"):
        ws = F / "workspace"
        check(ws.is_dir() and any(ws.iterdir()), "עותק workspace קיים (תיקיית המקור זמנית)")
    if (m.get("workspace") or {}).get("truncated"):
        warns.append("עותק workspace נקטע בתקרה — ראה manifest.json")
    for x in ok:
        print("  ✓", x)
    for x in warns:
        print("  !", x)
    for x in fails:
        print("  ✗", x)
    print(f"GATE: {'PASS' if not fails else 'FAIL'} · {len(ok)} עברו · {len(warns)} אזהרות · {len(fails)} נכשלו")
    return 0 if not fails else 1


def cmd_finalize(a):
    folder = Path(a.folder).expanduser().resolve()
    m = load_json(folder / "manifest.json")
    if not m:
        sys.exit("manifest.json missing — run collect first")
    md = read(folder / "HANDOFF.md")
    if FILL in md:
        print(f"HANDOFF.md still has {md.count(FILL)} <<FILL>> blocks — fill them first.")
        return 1
    clean = redact(md)
    if clean != md:
        write(folder / "HANDOFF.md", clean)
        md = clean
    short, full = build_prompts(folder, m, md)
    write(folder / "PROMPT.txt", short)
    write(folder / "PROMPT-FULL.md", redact(full))
    rc = cmd_verify(argparse.Namespace(folder=str(folder)))
    if rc != 0:
        print("finalize stopped: fix the ✗ items and run finalize again.")
        return rc
    zpath = None
    if not a.no_zip:
        zpath = folder.parent / f"{folder.name}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in L(folder).rglob("*"):
                if p.is_file():
                    z.write(p, Path(folder.name) / p.relative_to(L(folder)))
    idx = folder.parent / "INDEX.md"
    body = read(idx) if L(idx).is_file() else \
        "# Handoffs\n\n| נוצר | שם | סיבה | תיקייה |\n|---|---|---|---|\n"
    if str(folder) not in body:
        write(idx, body + f"| {m['created'][:16].replace('T', ' ')} | {m['name']} | {m.get('reason')} | `{folder}` |\n")
    write(folder.parent / "LATEST.txt", str(folder) + "\n")
    st = STATE / "state" / f"{m['session_id']}.json"
    s = load_json(st, {}) or {}
    s.update({"handoff_done": time.time(), "handoff_folder": str(folder)})
    write(st, json.dumps(s, ensure_ascii=False, indent=1))
    drill = STATE / "drill.json"
    if drill.is_file():
        drill.unlink()
        print("DRILL: completed, thresholds back to normal")
    print(f"READY: {folder}")
    if zpath:
        print(f"ZIP  : {zpath} ({human_size(zpath.stat().st_size)})")
    print("----- PROMPT.txt -----")
    print(short)
    return 0

# ---------------------------------------------------------------- note / status / latest


def cmd_note(a):
    u = read_usage() or {}
    u.update({"ts": time.time(), "source": "get_usage", "five_hour": a.five,
              "seven_day": a.week if a.week is not None else u.get("seven_day"),
              "five_hour_resets": a.resets or u.get("five_hour_resets")})
    write(USAGE_FILE, json.dumps(u, ensure_ascii=False, indent=1))
    print("noted:", usage_line(u))


def cmd_status(a):
    print("usage :", usage_line(read_usage()))
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    st = load_json(STATE / "state" / f"{sid}.json") if sid else None
    print("state :", json.dumps(st, ensure_ascii=False) if st else "—")
    print("config:", json.dumps(config(), ensure_ascii=False))


def cmd_find(a):
    """Sessions whose title contains the text (desktop titles live in the transcript tail)."""
    want = a.text.lower()
    rows = []
    for p in PROJECTS.glob("*/*.jsonl"):
        try:
            size = p.stat().st_size
            with open(p, "rb") as fh:
                fh.seek(max(0, size - 400_000))
                tail = fh.read().decode("utf-8", errors="ignore")
        except OSError:
            continue
        titles = re.findall(r'"customTitle":\s*"((?:[^"\\]|\\.)*)"', tail)
        title = json.loads(f'"{titles[-1]}"') if titles else ""
        cwd = re.findall(r'"cwd":\s*"((?:[^"\\]|\\.)*)"', tail)
        if want in title.lower() or want == p.stem:
            rows.append((p.stat().st_mtime, p.stem, title, json.loads(f'"{cwd[-1]}"') if cwd else "?", size))
    for mt, sid, title, cwd, size in sorted(rows, reverse=True)[:15]:
        print(f"{fmt(datetime.fromtimestamp(mt).astimezone())}  {sid}  {title}  ({human_size(size)})  {cwd}")
    if not rows:
        print(f"no session titled like '{a.text}'")


def cmd_drill(a):
    """A safe rehearsal: for the next N minutes the 5-hour threshold is 1%, so a session that works for
    a minute gets stopped and hands off exactly like the real thing. Ends itself after the handoff."""
    p = STATE / "drill.json"
    if a.action == "on":
        write(p, json.dumps({"until": time.time() + a.minutes * 60}))
        print(f"DRILL ON for {a.minutes} min: open a NEW session, give it any multi-step task, and after about a "
              f"minute of work it will stop and hand off. Ends by itself after the handoff (or: drill off).")
    else:
        if p.is_file():
            p.unlink()
        print("DRILL OFF: thresholds back to normal")


def cmd_latest(a):
    p = Path(config()["out_dir"]) / "LATEST.txt"
    print(p.read_text(encoding="utf-8").strip() if p.is_file() else "no handoffs yet")

# ---------------------------------------------------------------- terminal statusline bridge


def cmd_statusline(a):
    """The terminal hands plan limits only to the statusline. `on` wraps whatever statusline the user
    has with a pass-through tee (copied to a stable path, so plugin updates never break it)."""
    sp = CLAUDE / "settings.json"
    s = load_json(sp, {}) or {}
    cfg = load_json(CONFIG_FILE, {}) or {}
    tee = STATE / "statusline_tee.py"
    sl = (s.get("statusLine") or {}).get("command", "")
    active = "statusline_tee.py" in sl
    if a.action == "status":
        print("terminal bridge:", "ON" if active else "OFF", "·", usage_line(read_usage()))
        return 0
    if sp.is_file():
        write(CLAUDE / "backups" / f"settings.before-handoff-statusline.{int(time.time())}.json", read(sp))
    if a.action == "on":
        shutil.copy2(Path(__file__).resolve().parent / "statusline_tee.py", L(tee))
        if not active:
            cfg["statusline_passthrough"] = sl or None
            s["statusLine"] = {"type": "command",
                               "command": f'"{Path(sys.executable).as_posix()}" "{tee.as_posix()}"'}
        write(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=1))
        write(sp, json.dumps(s, ensure_ascii=False, indent=2))
        print("terminal bridge: ON (your statusline looks the same; takes effect in the next terminal session)")
    else:
        if active:
            if cfg.get("statusline_passthrough"):
                s["statusLine"] = {"type": "command", "command": cfg["statusline_passthrough"]}
            else:
                s.pop("statusLine", None)
            write(sp, json.dumps(s, ensure_ascii=False, indent=2))
        print("terminal bridge: OFF (statusline restored)")
    return 0

# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(prog="handoff", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--session", default="self")
    c.add_argument("--name")
    c.add_argument("--reason")
    c.add_argument("--cwd")
    c.add_argument("--copy-workspace", action="store_true")
    f = sub.add_parser("finalize")
    f.add_argument("folder")
    f.add_argument("--no-zip", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("folder")
    n = sub.add_parser("note")
    n.add_argument("--five", type=float, required=True)
    n.add_argument("--week", type=float)
    n.add_argument("--resets")
    fd = sub.add_parser("find")
    fd.add_argument("text")
    sl = sub.add_parser("statusline")
    sl.add_argument("action", choices=["on", "off", "status"])
    dr = sub.add_parser("drill")
    dr.add_argument("action", choices=["on", "off"])
    dr.add_argument("--minutes", type=int, default=30)
    for name in ("status", "latest"):
        sub.add_parser(name)
    a, extra = ap.parse_known_args()
    extra = [x for x in extra if x not in (".", ",", ";")]  # punctuation copied along with a command
    if extra:
        ap.error("unrecognized arguments: " + " ".join(extra))
    fn = {"collect": cmd_collect, "finalize": cmd_finalize, "verify": cmd_verify, "note": cmd_note,
          "find": cmd_find, "status": cmd_status, "latest": cmd_latest, "statusline": cmd_statusline,
          "drill": cmd_drill}[a.cmd]
    sys.exit(fn(a) or 0)


if __name__ == "__main__":
    main()
