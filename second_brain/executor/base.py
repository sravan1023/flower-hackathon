"""Executor base: run(brief) -> result. Hub mode only hands back the brief; the user acts on it."""

from __future__ import annotations

from .. import runtime


def run(brief: dict) -> dict:
    """Never performs a final action. In local mode an optional aside executor may pre-fill pages."""
    if not brief or not brief.get("text") or "ACTION BRIEF" not in brief["text"]:
        return {"ok": False, "status": "rejected", "reason": "no approved brief"}
    if runtime.mode() == "local":
        try:
            from . import aside  # optional, owned by the local-mode workstream

            fn = getattr(aside, "run", None)
            if fn:
                res = fn(brief)
                if isinstance(res, dict):
                    return res
        except Exception as e:  # noqa: BLE001 - hub behaviour is the safe fallback
            runtime.log({"task": "executor", "error": str(e)[:200]})
    return {"ok": True, "status": "brief_only", "card_id": brief.get("card_id"), "brief": brief["text"]}
