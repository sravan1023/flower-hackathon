"""Call the local embed service. Every function returns None on any failure (hub mode stays intact)."""

from __future__ import annotations

import os


def _base() -> str:
    return os.environ.get("EMBED_SERVICE", "http://localhost:8765")


def _post(path: str, payload: dict, timeout: float = 30):
    try:
        import httpx

        r = httpx.post(_base() + path, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def local_embed(texts: list[str]) -> list[list[float]] | None:
    d = _post("/embed", {"texts": texts})
    v = d.get("vectors") if isinstance(d, dict) else None
    return v if v and len(v) == len(texts) else None


def local_clip_score(image_paths: list[str], texts: list[str]) -> list[list[float]] | None:
    d = _post("/clip/score", {"image_paths": image_paths, "texts": texts}, timeout=120)
    m = d.get("matrix") if isinstance(d, dict) else None
    return m if m else None
