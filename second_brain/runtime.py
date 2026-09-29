"""Mode detection, data dir, env loading, run log, profile storage."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

PKG = Path(__file__).parent


def data_dir() -> Path:
    for base in (Path(os.environ.get("SECOND_BRAIN_DATA", "data")), Path(tempfile.gettempdir()) / "second_brain"):
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base
        except OSError:
            continue
    raise RuntimeError("no writable data dir")


def load_env() -> None:
    """Keys come from env first, then data/.env (gitignored)."""
    f = data_dir() / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _reachable(url: str) -> bool:
    try:
        import httpx

        return httpx.get(url, timeout=1.5).status_code < 500
    except Exception:
        return False


def mode() -> str:
    """'local' only if SECOND_BRAIN_LOCAL=1 AND aside + embed service are reachable."""
    if os.environ.get("SECOND_BRAIN_LOCAL") != "1":
        return "hub"
    if shutil.which("aside") and _reachable(os.environ.get("EMBED_SERVICE", "http://localhost:8765") + "/health"):
        return "local"
    return "hub"


def log(event: dict[str, Any]) -> None:
    try:
        with (data_dir() / "run_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **event}) + "\n")
    except OSError:
        pass


def read_log() -> list[dict]:
    p = data_dir() / "run_log.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_profile() -> dict:
    p = data_dir() / "profile.json"
    if not p.exists():
        shutil.copy(PKG / "seed" / "profile.example.json", p)
    return json.loads(p.read_text(encoding="utf-8"))


def save_profile(profile: dict) -> None:
    (data_dir() / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")


def save_state(context: Any, key: str, obj: Any) -> None:
    """Persist across turns: Flower context.state when available, plus a file."""
    (data_dir() / f"{key}.json").write_text(json.dumps(obj), encoding="utf-8")
    try:
        from flwr.app import ConfigRecord

        context.state[key] = ConfigRecord({"json": json.dumps(obj)})
    except Exception:
        pass


def load_state(context: Any, key: str, default: Any = None) -> Any:
    try:
        return json.loads(context.state[key]["json"])
    except Exception:
        pass
    p = data_dir() / f"{key}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
