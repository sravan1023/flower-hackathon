"""Verify the newest FAB: size, file types, forbidden paths, secret-looking strings, metadata.

Does not build unless no *.fab exists (then runs `uv run flwr build`).
Exit codes: 0 ok, 1 failures, 2 warnings only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 1024 * 1024
ALLOWED_EXT = {".py", ".toml", ".md", ".yaml", ".yml", ".json", ".jsonl"}
ALLOWED_NAMES = {"LICENSE"}
ALLOWED_PATHS = {".info/CONTENT"}  # Flower-generated FAB metadata
FORBIDDEN = ("data/", ".env", "browser-profile", ".gguf")
SECRET_RE = re.compile(rb"sk-[A-Za-z0-9_\-]{16,}|fw_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}")
PLACEHOLDER = "CHANGE_ME_FLOWER_USERNAME"


def newest_fab() -> Path:
    fabs = sorted(ROOT.glob("*.fab"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not fabs:
        print("no .fab found, running: uv run flwr build")
        env = {**os.environ, "PYTHONUTF8": "1"}
        subprocess.run(["uv", "run", "flwr", "build"], cwd=ROOT, check=True, env=env)
        fabs = sorted(ROOT.glob("*.fab"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not fabs:
        sys.exit("build produced no .fab")
    return fabs[0]


def main() -> int:
    fab = newest_fab()
    fails: list[str] = []
    warns: list[str] = []
    size = fab.stat().st_size
    print(f"FAB: {fab.name} ({size} bytes)")
    if size >= MAX_BYTES:
        fails.append(f"size {size} >= 1 MiB")

    with zipfile.ZipFile(fab) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        print("files:")
        for n in names:
            print(f"  {n}")
        for n in names:
            low = n.lower()
            ext = os.path.splitext(low)[1]
            if ext not in ALLOWED_EXT and os.path.basename(n) not in ALLOWED_NAMES and n not in ALLOWED_PATHS:
                fails.append(f"disallowed file type: {n}")
            for bad in FORBIDDEN:
                if bad in low or (bad == "data/" and low.startswith("data/")):
                    fails.append(f"forbidden path ({bad}): {n}")
            m = SECRET_RE.search(z.read(n))
            if m:
                fails.append(f"secret-like string in {n}: {m.group(0)[:6].decode(errors='ignore')}...")
        if not any(os.path.basename(n).upper().startswith("LICENSE") for n in names):
            fails.append("no LICENSE file in FAB")
        pp = next((n for n in names if n.endswith("pyproject.toml")), None)
        if pp is None:
            fails.append("no pyproject.toml in FAB")
        else:
            cfg = tomllib.loads(z.read(pp).decode("utf-8"))
            if not str(cfg.get("project", {}).get("description", "")).strip():
                fails.append("pyproject description is empty")
            pub = cfg.get("tool", {}).get("flwr", {}).get("app", {}).get("publisher", "")
            if pub == PLACEHOLDER:
                warns.append(f"publisher is still {PLACEHOLDER} (set before publish)")

    for w in warns:
        print("WARNING:", w)
    for f in fails:
        print("FAIL:", f)
    if fails:
        return 1
    if warns:
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
