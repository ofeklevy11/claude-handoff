#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Builds the plugin ZIP for "Upload a plugin" (claude.ai / Claude desktop): only what the plugin runs on,
with `.claude-plugin/plugin.json` at the ZIP root, LF endings kept and scripts marked executable.

  python tools/build_zip.py                 -> dist/handoff-<version>.zip
  python tools/build_zip.py --out X.zip
  python tools/build_zip.py --check Y.zip   the uploader's rule alone, on any ZIP (exit 1 when it would refuse it)

GitHub's own "Download ZIP" of the repo passes the same rule too: since 1.0.6 the repo root is the plugin.
"""
import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = (".claude-plugin/plugin.json", "hooks/", "skills/", "README.md", "LICENSE")
MANIFEST = ".claude-plugin/plugin.json"


def plugin_files():
    """Tracked files when this is a git checkout (never caches or local leftovers), else a walk without caches."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, timeout=30, check=True).stdout
        names = [n for n in out.decode("utf-8").split("\0") if n]
    except (OSError, subprocess.SubprocessError):
        names = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    keep = [n for n in names if any(n == i or (i.endswith("/") and n.startswith(i)) for i in INCLUDE)]
    return sorted(n for n in keep if (ROOT / n).is_file())


def upload_rule(zpath):
    """The uploader's rule: `.claude-plugin/plugin.json` at the ZIP root, or inside a single top-level directory.
    Returns (ok, where-or-reason)."""
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.startswith("__MACOSX/")]
        if MANIFEST in names:
            where = MANIFEST
        else:
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) != 1 or not all("/" in n for n in names):
                return False, f"no {MANIFEST} at the root, and {len(tops)} top-level entries (needs exactly 1 folder)"
            where = f"{tops.pop()}/{MANIFEST}"
            if where not in names:
                return False, f"no {MANIFEST} inside the single top-level folder"
        try:
            pl = json.loads(z.read(where).decode("utf-8"))
        except ValueError as e:
            return False, f"{where} is not valid JSON ({e})"
        if not isinstance(pl, dict) or not pl.get("name"):
            return False, f"{where} has no plugin name"
        return True, where


def build(out):
    version = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))["version"]
    out = Path(out or ROOT / "dist" / f"handoff-{version}.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    files = plugin_files()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in files:
            info = zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if n.endswith((".sh", ".py")) else 0o100644) << 16
            z.writestr(info, (ROOT / n).read_bytes())  # bytes as committed: run.sh keeps its LF endings
    return out, files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--check", metavar="ZIP")
    a = ap.parse_args()
    if a.check:
        ok, msg = upload_rule(a.check)
        print(("OK   " if ok else "FAIL ") + f"{a.check}: {msg}")
        return 0 if ok else 1
    out, files = build(a.out)
    ok, msg = upload_rule(out)
    print(f"{out} ({len(files)} files, {out.stat().st_size // 1024} KB) · upload rule: {'OK' if ok else 'FAIL'} ({msg})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
