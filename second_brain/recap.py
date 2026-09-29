"""Structured text recap of a session, built from session state and run_log."""

from __future__ import annotations

from . import runtime

SECRET_PROVIDERS = ("fireworks", "claude")


def providers_used(since: float = 0.0) -> dict:
    used: dict[str, int] = {}
    try:
        for e in runtime.read_log():
            if (e.get("ts") or 0) >= since and e.get("provider") and not e.get("error") and e["provider"] != "rule-based-default":
                used[e["provider"]] = used.get(e["provider"], 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return used


def build(session: dict, profile: dict) -> str:
    if not session.get("goal"):
        return "No goal set yet."
    g = session["goal"] if isinstance(session["goal"], dict) else {"goal": str(session["goal"])}
    before, after = session.get("alignment_before"), session.get("alignment_after")
    cards = [c for c in session.get("cards", []) if isinstance(c, dict)]
    L = [f"**Recap** - goal: {g.get('goal', '?')} (by {g.get('deadline', 'n/a')})", f"Alignment: {before} -> {after if after is not None else 'pending decisions'}", "", "Decisions:"]
    for c in cards:
        extra = f" - picked '{c['chosen']}' over '{c.get('title', '?')}'" if c.get("chosen") else ""
        L.append(f"- #{c.get('id', '?')} {c.get('title', '?')}: {c.get('status', '?')}{extra}")
    if not cards:
        L.append("- none yet")
    top = sorted((c for c in cards if isinstance(c.get("score"), (int, float))), key=lambda c: -c["score"])[:3]
    L += ["", "Top scores: " + ("; ".join(f"#{c.get('id', '?')} {c['score']:.2f}" for c in top) or "n/a")]
    issued = session.get("briefs_issued", [])
    L.append("Briefs issued: " + (", ".join(f"#{i}" for i in issued) or "none"))
    used = providers_used(session.get("started", 0.0))
    secret = {k: v for k, v in used.items() if k in SECRET_PROVIDERS}
    L.append(f"Scorer backend: {session.get('scorer', 'n/a')}")
    L.append("Secret-keyed providers used: " + (", ".join(f"{k} x{v}" for k, v in secret.items()) if secret else "no (flower runtime / local models only)"))
    prefs = [p for p in ((profile.get("preferences") or {}).get("picked_over") or []) if isinstance(p, dict)]
    if prefs:
        L.append("Overrides remembered: " + "; ".join(f"{p.get('picked', '?')} over {p.get('over', '?')}" for p in prefs[-3:]))
    return "\n".join(L)
