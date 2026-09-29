"""One interface over providers: flower (runtime), kimi/minimax (Nebius), fireworks, claude.

complete(task, messages, json_schema=None, default=None) -> dict | str
embed(texts) -> list[list[float]]
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import yaml

from . import runtime

_CFG: dict | None = None
_OVERRIDE: dict[str, str] = {}
_DEAD: dict[str, float] = {}  # provider -> time it last failed hard (circuit breaker)
DEAD_FOR = 120.0
LAST_PROVIDER: str | None = None  # provider that answered the most recent complete() (None = rule-based default)
PROVIDERS_USED: set[str] = set()


class RouterError(RuntimeError):
    pass


def cfg() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = yaml.safe_load((runtime.PKG / "config" / "models.yaml").read_text(encoding="utf-8"))
    return _CFG


def configure(run_config: Any) -> None:
    """Apply run-config overrides (agent.model for the flower provider)."""
    m = run_config.get("agent.model") if run_config else None
    if m:
        _OVERRIDE["flower"] = str(m)


def _model(name: str) -> str:
    p = cfg()["providers"][name]
    return _OVERRIDE.get(name) or (os.environ.get(p.get("model_env", "")) if p.get("model_env") else None) or p["model"]


def _base_url(name: str) -> str | None:
    p = cfg()["providers"][name]
    return (os.environ.get(p["base_url_env"]) if p.get("base_url_env") else None) or p.get("base_url")


def available(name: str) -> bool:
    p = cfg()["providers"][name]
    if not os.environ.get(p["key_env"]):
        return False
    if p.get("kind") == "anthropic":
        return True
    return bool(_base_url(name))


def _openai(name: str):
    from openai import OpenAI

    key = os.environ[cfg()["providers"][name]["key_env"]]
    if name == "flower":
        return OpenAI(base_url=_base_url(name), api_key=key, max_retries=0, timeout=60)
    return OpenAI(base_url=_base_url(name), api_key=key, max_retries=1, timeout=60)


_TOKENISH = re.compile(r"[A-Za-z0-9_\-\.=+/]{30,}")


def _redact(text: str) -> str:
    """Never let key-looking strings reach logs/errors."""
    return _TOKENISH.sub("[redacted]", str(text))[:200]


def _call(name: str, messages: list[dict]) -> str:
    p = cfg()["providers"][name]
    if p.get("kind") == "anthropic":
        import anthropic

        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        kw = {"system": system} if system else {}
        r = anthropic.Anthropic(api_key=os.environ[p["key_env"]]).messages.create(
            model=_model(name), max_tokens=2000, messages=rest, **kw
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    client = _openai(name)
    if name == "flower":  # runtime speaks the Responses API (streamed)
        parts: list[str] = []
        for ev in client.responses.create(model=_model(name), input=messages, stream=True):
            if ev.type == "response.output_text.delta":
                parts.append(ev.delta)
            elif ev.type in ("error", "response.failed"):
                raise RuntimeError(f"flower model failed: {_redact(str(ev))}")
        return "".join(parts)
    if p.get("api_style") == "responses":
        return (client.responses.create(model=_model(name), input=messages).output_text or "").strip()
    r = client.chat.completions.create(model=_model(name), messages=messages)
    return r.choices[0].message.content or ""


def _parse_json(text: str) -> Any:
    """Strict JSON, fenced JSON, or the first JSON value embedded in prose."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):  # first decodable object/array (handles prose with stray braces)
        if ch in "{[":
            try:
                return dec.raw_decode(text[i:])[0]
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("no JSON found", text, 0)


_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}


def validate(obj: Any, schema: dict, path: str = "$") -> None:
    """Minimal JSON-schema subset: type, required, properties, items."""
    t = schema.get("type")
    if t:
        if t not in _TYPES:
            raise ValueError(f"{path}: unsupported type {t}")
        if not isinstance(obj, _TYPES[t]) or (t in ("number", "integer") and isinstance(obj, bool)):
            raise ValueError(f"{path}: expected {t}")
        if t == "number" and obj != obj:
            raise ValueError(f"{path}: NaN")
    if t == "object":
        for k in schema.get("required", []):
            if k not in obj:
                raise ValueError(f"{path}.{k}: missing")
        for k, s in schema.get("properties", {}).items():
            if k in obj:
                validate(obj[k], s, f"{path}.{k}")
    if t == "array" and "items" in schema:
        for i, x in enumerate(obj):
            validate(x, schema["items"], f"{path}[{i}]")


_NODEFAULT = object()


def complete(task: str, messages: list[dict], json_schema: dict | None = None, default: Any = _NODEFAULT) -> Any:
    """Route by task, fall back down the chain. JSON: validate, retry once, then `default`."""
    global LAST_PROVIDER
    runtime.load_env()
    if json_schema:
        messages = messages + [
            {"role": "system", "content": "Reply with ONLY valid JSON matching this schema: " + json.dumps(json_schema)}
        ]
    for name in cfg()["tasks"].get(task, []):
        if not available(name) or time.time() - _DEAD.get(name, 0.0) < DEAD_FOR:
            continue
        msgs = list(messages)
        for attempt in (1, 2):
            t0 = time.time()
            try:
                out = _call(name, msgs)
                if not isinstance(out, str):
                    raise RuntimeError("provider returned non-text")
                res = out
                if json_schema:
                    res = _parse_json(out)
                    validate(res, json_schema)
                runtime.log({"task": task, "provider": name, "model": _model(name), "latency": round(time.time() - t0, 2), "attempt": attempt})
                LAST_PROVIDER = name
                PROVIDERS_USED.add(name)
                return res
            except (ValueError, json.JSONDecodeError) as e:  # bad JSON / schema: retry once
                runtime.log({"task": task, "provider": name, "error": _redact(e), "attempt": attempt})
                msgs = msgs + [{"role": "user", "content": f"Invalid ({e}). Return only valid JSON."}]
            except Exception as e:  # noqa: BLE001 - provider/network errors: next provider
                _DEAD[name] = time.time()  # one timeout per provider, not one per call
                runtime.log({"task": task, "provider": name, "error": _redact(e), "attempt": attempt})
                break
    LAST_PROVIDER = None
    if default is not _NODEFAULT:  # falsy defaults ({}, [], "") are valid; only "not passed" raises
        runtime.log({"task": task, "provider": "rule-based-default"})
        return default
    raise RouterError(f"no provider produced a result for task {task!r}")


def embed(texts: list[str]) -> list[list[float]]:
    """Fireworks embeddings over HTTP. Raises RouterError if unavailable (caller falls back)."""
    runtime.load_env()
    if not available("fireworks"):
        raise RouterError("no FIREWORKS_API_KEY")
    t0 = time.time()
    p = cfg()["providers"]["fireworks"]
    try:
        r = _openai("fireworks").embeddings.create(model=p["embed_model"], input=texts)
    except Exception as e:  # noqa: BLE001
        runtime.log({"task": "embed", "provider": "fireworks", "error": _redact(e)})
        raise RouterError(str(e)) from e
    runtime.log({"task": "embed", "provider": "fireworks", "model": p["embed_model"], "latency": round(time.time() - t0, 2)})
    return [d.embedding for d in r.data]
