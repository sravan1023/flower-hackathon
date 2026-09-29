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
    try:
        f = data_dir() / ".env"
        lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    except Exception:
        return
    for line in lines:
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
    except Exception:
        pass


def read_log() -> list[dict]:
    try:
        p = data_dir() / "run_log.jsonl"
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    except Exception:
        return []


def load_profile() -> dict:
    seed = PKG / "seed" / "profile.example.json"
    try:
        p = data_dir() / "profile.json"
        if not p.exists():
            shutil.copy(seed, p)
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # unwritable/corrupt: fall back to the bundled seed
        return json.loads(seed.read_text(encoding="utf-8"))


def save_profile(profile: dict) -> None:
    try:
        (data_dir() / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    except Exception:
        pass


def save_state(context: Any, key: str, obj: Any) -> None:
    """Persist across turns: Flower context.state when available, plus a file."""
    try:
        (data_dir() / f"{key}.json").write_text(json.dumps(obj), encoding="utf-8")
    except Exception:  # read-only FS must not break the turn
        pass
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
    try:
        p = data_dir() / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


_T0 = time.time()


def stage(name: str) -> None:
    """Visible in `flwr log`: progress + elapsed seconds (helps find hangs on SuperGrid)."""
    print(f"[stage] {name} t={time.time() - _T0:.1f}s", flush=True)
    log({"task": "stage", "name": name})
