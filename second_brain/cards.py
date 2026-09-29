"""Decision cards: build, render, parse the user's reply, apply overrides. Nothing runs without approval."""

from __future__ import annotations

import re
from typing import Any

LETTERS = "abc"


def make_card(cid: int, agent: str, title: str, score: float, reason: str, alternatives: list[dict], item: dict | None = None, detail: str = "") -> dict:
    """alternatives: [{title, score}] best first; only the top 3 are kept."""
    return {
        "id": cid,
        "agent": agent,
        "title": title,
        "score": round(score, 3),
        "why": f"score {score:.2f}: {reason}",
        "detail": detail,
        "alternatives": [{"label": LETTERS[i], "title": a["title"], "score": round(a.get("score", 0), 3), "detail": a.get("detail", "")} for i, a in enumerate(alternatives[:3])],
        "options": ["approve", "edit", "skip"],
        "item": item or {"text": title, "hours": 2, "kind": "calendar"},
        "status": "pending",
        "chosen": None,
    }


def render(cards: list[dict]) -> str:
    lines = ["**Decision cards** (you decide; reply like `approve 1, 3, pick 2b, skip 4`)", ""]
    for c in cards:
        lines.append(f"{c['id']}. [{c['agent']}] **{c['title']}**  \n   {c['why']}")
        for a in c["alternatives"]:
            lines.append(f"   - {c['id']}{a['label']}: {a['title']} ({a['score']:.2f})")
        lines.append(f"   options: {' / '.join(c['options'])}   status: {c['status']}")
    return "\n".join(lines)


def parse_reply(text: str) -> dict[str, Any]:
    """'approve 1, 3, pick 2b, skip 4' -> {approve:[1,3], pick:{2:'b'}, skip:[4], edit:[]}."""
    t = text.lower()
    out: dict[str, Any] = {"approve": [], "skip": [], "edit": [], "pick": {}}
    for m in re.finditer(r"pick\s+(\d+)\s*([a-c])", t):
        out["pick"][int(m.group(1))] = m.group(2)
    t = re.sub(r"pick\s+\d+\s*[a-c]", " ", t)
    for m in re.finditer(r"(approve|skip|edit)\s+((?:all|\d+)(?:\s*(?:,|and|&)\s*\d+)*)", t):
        ids = "all" if m.group(2) == "all" else [int(x) for x in re.findall(r"\d+", m.group(2))]
        out[m.group(1)] += [ids] if ids == "all" else ids
    return out


def has_decisions(text: str) -> bool:
    d = parse_reply(text)
    return bool(d["approve"] or d["skip"] or d["edit"] or d["pick"])


def apply(cards: list[dict], decisions: dict, profile: dict) -> list[dict]:
    """Update card statuses; store overrides in profile.preferences to feed the next ranking."""
    prefs = profile.setdefault("preferences", {"liked": [], "skipped": [], "picked_over": []})
    for k in ("liked", "skipped", "picked_over"):
        prefs.setdefault(k, [])
    by_id = {c["id"]: c for c in cards}
    pending = [c["id"] for c in cards if c["status"] == "pending"]
    for cid in decisions["approve"]:
        for i in (pending if cid == "all" else [cid]):
            c = by_id.get(i)
            if c and c["status"] == "pending":
                c["status"] = "approved"
                prefs["liked"].append(c["title"])
    for cid in decisions["edit"]:
        if cid in by_id:
            by_id[cid]["status"] = "edit"  # user supplies replacement text next turn
    for cid in decisions["skip"]:
        c = by_id.get(cid)
        if c:
            c["status"] = "skipped"
            prefs["skipped"].append(c["title"])
    for cid, letter in decisions["pick"].items():
        c = by_id.get(cid)
        alt = next((a for a in (c or {}).get("alternatives", []) if a["label"] == letter), None)
        if c and alt:
            c["status"] = "approved"
            c["chosen"] = alt["title"]
            c["item"] = {**c["item"], "text": alt["title"]}
            prefs["picked_over"].append({"picked": alt["title"], "over": c["title"]})
    for k in prefs:
        prefs[k] = prefs[k][-30:]
    return cards
