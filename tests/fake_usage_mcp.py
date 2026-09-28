#!/usr/bin/env python3
"""Stand-in for the desktop app's `ccd_session_mgmt.get_usage` tool, for the e2e test.
Returns the plan-usage JSON the real tool returns, walking FAKE_USAGE_SEQUENCE (e.g. "35,86") one
step per call and staying on the last value. Minimal MCP over stdio (newline-delimited JSON-RPC)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

SEQ = [int(x) for x in os.environ.get("FAKE_USAGE_SEQUENCE", "35,86").split(",")]
COUNTER = os.environ.get("FAKE_USAGE_COUNTER")


def next_percent():
    n = 0
    if COUNTER and os.path.exists(COUNTER):
        n = int(open(COUNTER).read() or 0)
    if COUNTER:
        open(COUNTER, "w").write(str(n + 1))
    return SEQ[min(n, len(SEQ) - 1)]


def usage():
    pct = next_percent()
    reset = datetime.now(timezone.utc) + timedelta(minutes=47)
    return {"plan": {"status": "ok", "plan": "Max", "windows": [
        {"label": "5-hour limit", "percentUsed": pct, "resetsAt": reset.isoformat(), "resetsIn": "47m"},
        {"label": "Weekly · all models", "percentUsed": 31, "resetsAt": (reset + timedelta(days=3)).isoformat(),
         "resetsIn": "3d 1h"}]},
        "context": {"session": "self", "status": "ok", "percentUsed": 12}}


TOOL = {"name": "get_usage", "description": "The account's Claude Code plan limits (5-hour, weekly) with percent "
        "used and reset time, and how full this session's context window is. Read-only.",
        "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}}}


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        continue
    if method == "initialize":
        reply(mid, {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "ccd_session_mgmt", "version": "0.0.1"}})
    elif method == "tools/list":
        reply(mid, {"tools": [TOOL]})
    elif method == "tools/call":
        reply(mid, {"content": [{"type": "text", "text": json.dumps(usage(), ensure_ascii=False, indent=2)}]})
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "no"}}) + "\n")
        sys.stdout.flush()
