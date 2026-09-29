"""Thin client for a local llama.cpp server (OpenAI-compatible). Health logging only."""

from __future__ import annotations

import os

from .. import runtime


def _url() -> str:
    return os.environ.get("LIZZY_URL", "http://localhost:8080").rstrip("/")


def is_available() -> bool:
    try:
        import httpx

        return httpx.get(_url() + "/health", timeout=1.5).status_code < 500
    except Exception:
        return False


def chat(prompt: str, max_tokens: int = 128) -> str | None:
    try:
        import httpx

        r = httpx.post(
            _url() + "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        runtime.log({"task": "lizzy", "error": str(e)[:150]})
        return None


def log_health() -> bool:
    ok = is_available()
    runtime.log({"task": "lizzy", "available": ok, "url": _url()})
    return ok
