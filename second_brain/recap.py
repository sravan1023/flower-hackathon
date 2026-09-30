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


def done_for_you(session: dict) -> list[str]:
    """Lines for the 'Done for you' section (local WhatsApp/calendar loop); [] when nothing happened. No phone/email."""
    L: list[str] = []
    for ev in session.get("calendar_created") or []:
        if isinstance(ev, (list, tuple)) and len(ev) >= 2:
            L.append(f"- Calendar event: {ev[0]} ({ev[1]})")
    d = session.get("demo")
    if isinstance(d, dict):
        for t in d.get("registered") or []:
            L.append(f"- Registered for event: {t}")
        if d.get("calendar"):
            L.append(f"- Calendar blocks added: {d['calendar']}")
        if d.get("post_url"):
            L.append(f"- Substack post: {d['post_url']}")
    wc = session.get("wa_confirm")
    if isinstance(wc, dict):
        L.append(f"- Confirmed over WhatsApp: {wc.get('approved', 0)} approved, {wc.get('changed', 0)} changed after alternatives")
    cmds = [c for c in session.get("wa_cmds") or [] if isinstance(c, str)]
    if cmds:
        counts: dict[str, int] = {}
        for c in cmds:
            counts[c] = counts.get(c, 0) + 1
        L.append("- Commands received: " + ", ".join(f"{k} x{v}" for k, v in counts.items()))
    return ["Done for you:"] + L if L else []


def build(session: dict, profile: dict, compact: bool = False) -> str:
    if not session.get("goal"):
        return "No goal set yet."
    if compact:  # WhatsApp: short, keeps the Done-for-you block
        cards = [c for c in session.get("cards", []) if isinstance(c, dict)]
        counts: dict[str, int] = {}
        for c in cards:
            counts[c.get("status", "?")] = counts.get(c.get("status", "?"), 0) + 1
        g = session["goal"].get("goal", "?") if isinstance(session["goal"], dict) else str(session["goal"])
        L = [f"Recap - goal: {str(g)[:80]}", "Cards: " + (", ".join(f"{v} {k}" for k, v in counts.items()) or "none")]
        return chr(10).join(L + (done_for_you(session) or ["Done for you: nothing yet"]))
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
    dfy = done_for_you(session)
    if dfy:
        L += [""] + dfy
    prefs = [p for p in ((profile.get("preferences") or {}).get("picked_over") or []) if isinstance(p, dict)]
    if prefs:
        L.append("Overrides remembered: " + "; ".join(f"{p.get('picked', '?')} over {p.get('over', '?')}" for p in prefs[-3:]))
    return "\n".join(L)
