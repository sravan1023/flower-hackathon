"""One interface over three providers: flower (runtime), fireworks, claude.

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
    return _OVERRIDE.get(name) or cfg()["providers"][name]["model"]


def available(name: str) -> bool:
    p = cfg()["providers"][name]
    if name == "flower":
        return bool(os.environ.get("FLWR_RUNTIME_BASE_URL") and os.environ.get("FLWR_RUNTIME_API_KEY"))
    return bool(os.environ.get(p["key_env"]))


def _openai(name: str):
    from openai import OpenAI

    p = cfg()["providers"][name]
    if name == "flower":
        return OpenAI(base_url=os.environ["FLWR_RUNTIME_BASE_URL"], api_key=os.environ["FLWR_RUNTIME_API_KEY"], max_retries=0)
    return OpenAI(base_url=p["base_url"], api_key=os.environ[p["key_env"]], max_retries=1, timeout=60)


def _call(name: str, messages: list[dict]) -> str:
    if name == "claude":
        import anthropic

        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        kw = {"system": system} if system else {}
        r = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]).messages.create(
            model=_model("claude"), max_tokens=2000, messages=rest, **kw
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    client = _openai(name)
    if name == "flower":  # runtime speaks the Responses API
        return client.responses.create(model=_model(name), input=messages).output_text
    r = client.chat.completions.create(model=_model(name), messages=messages)
    return r.choices[0].message.content or ""


def _parse_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}


def validate(obj: Any, schema: dict, path: str = "$") -> None:
    """Minimal JSON-schema subset: type, required, properties, items."""
    t = schema.get("type")
    if t and not isinstance(obj, _TYPES[t]):
        raise ValueError(f"{path}: expected {t}")
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


def complete(task: str, messages: list[dict], json_schema: dict | None = None, default: Any = None) -> Any:
    """Route by task, fall back down the chain. JSON: validate, retry once, then `default`."""
    runtime.load_env()
    if json_schema:
        messages = messages + [
            {"role": "system", "content": "Reply with ONLY valid JSON matching this schema: " + json.dumps(json_schema)}
        ]
    for name in cfg()["tasks"][task]:
        if not available(name):
            continue
        msgs = list(messages)
        for attempt in (1, 2):
            t0 = time.time()
            try:
                out = _call(name, msgs)
                res = out
                if json_schema:
                    res = _parse_json(out)
                    validate(res, json_schema)
                runtime.log({"task": task, "provider": name, "model": _model(name), "latency": round(time.time() - t0, 2), "attempt": attempt})
                return res
            except (ValueError, json.JSONDecodeError) as e:  # bad JSON / schema: retry once
                runtime.log({"task": task, "provider": name, "error": str(e)[:200], "attempt": attempt})
                msgs = msgs + [{"role": "user", "content": f"Invalid ({e}). Return only valid JSON."}]
            except Exception as e:  # noqa: BLE001 - provider/network errors: next provider
                runtime.log({"task": task, "provider": name, "error": str(e)[:200], "attempt": attempt})
                break
    if default is not None:
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
        runtime.log({"task": "embed", "provider": "fireworks", "error": str(e)[:200]})
        raise RouterError(str(e)) from e
    runtime.log({"task": "embed", "provider": "fireworks", "model": p["embed_model"], "latency": round(time.time() - t0, 2)})
    return [d.embedding for d in r.data]
