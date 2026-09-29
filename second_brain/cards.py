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
        "alternatives": [{"label": LETTERS[i], "title": a["title"], "score": round(a.get("score", 0), 3), "detail": a.get("detail", ""), **({"item": a["item"]} if a.get("item") else {})} for i, a in enumerate(alternatives[:3])],
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


_IDS = r"(?:all|#?\d+(?:\s*-\s*#?\d+)?)(?:(?:\s*,\s*|\s+and\s+|\s*&\s*|\s+)#?\d+(?:\s*-\s*#?\d+)?)*"


def _expand(chunk: str) -> list[int]:
    ids: list[int] = []
    for a, b in re.findall(r"(\d+)(?:\s*-\s*#?(\d+))?", chunk):
        lo, hi = int(a), int(b) if b else int(a)
        ids += list(range(lo, min(hi, lo + 50) + 1)) if hi >= lo else [lo]
    return ids


def parse_reply(text: str) -> dict[str, Any]:
    """'approve 1, 3, pick 2b, skip 4' -> {approve:[1,3], pick:{2:'b'}, skip:[4], edit:[]}. 'all' may appear in a list."""
    t = (text or "").lower()
    out: dict[str, Any] = {"approve": [], "skip": [], "edit": [], "pick": {}}
    for m in re.finditer(r"\bpick\s+#?(\d+)\s*([a-c])\b", t):
        out["pick"][int(m.group(1))] = m.group(2)
    t = re.sub(r"\bpick\s+#?\d+\s*[a-c]\b", " ", t)
    for m in re.finditer(rf"\b(approve|skip|edit)\s+({_IDS})", t):
        chunk = m.group(2)
        out[m.group(1)] += ["all"] if chunk.startswith("all") else _expand(chunk)
    return out


def has_decisions(text: str) -> bool:
    d = parse_reply(text)
    return bool(d["approve"] or d["skip"] or d["edit"] or d["pick"])


def apply(cards: list[dict], decisions: dict, profile: dict) -> list[dict]:
    """Update card statuses; store overrides in profile.preferences to feed the next ranking.

    Only pending/edit cards can change: an approved (brief may be issued) or skipped card is final.
    Unknown ids are ignored.
    """
    prefs = profile.get("preferences")
    if not isinstance(prefs, dict):
        prefs = profile["preferences"] = {}
    for k in ("liked", "skipped", "picked_over"):
        prefs.setdefault(k, [])
    open_ = {c["id"]: c for c in cards if c["status"] in ("pending", "edit")}

    def targets(ids: list) -> list[int]:
        out: list[int] = []
        for i in ids:
            out += sorted(open_) if i == "all" else [i]
        return out

    def remember(key: str, val: Any) -> None:
        if val in prefs[key]:
            prefs[key].remove(val)
        prefs[key].append(val)

    for i in targets(decisions.get("approve", [])):
        c = open_.get(i)
        if c and c["status"] == "pending":
            c["status"] = "approved"
            remember("liked", c["title"])
    for i in targets(decisions.get("edit", [])):
        c = open_.get(i)
        if c and c["status"] == "pending":
            c["status"] = "edit"  # user supplies replacement text next turn
    for i in targets(decisions.get("skip", [])):
        c = open_.get(i)
        if c and c["status"] in ("pending", "edit"):
            c["status"] = "skipped"
            remember("skipped", c["title"])
    for cid, letter in decisions.get("pick", {}).items():
        c = open_.get(cid)
        alt = next((a for a in (c or {}).get("alternatives", []) if a["label"] == letter), None)
        if c and alt and c["status"] in ("pending", "edit"):
            c["status"] = "approved"
            c["chosen"] = alt["title"]
            c["item"] = {**c["item"], **(alt.get("item") or {"text": alt["title"]})}
            remember("picked_over", {"picked": alt["title"], "over": c["title"]})
    for k in prefs:
        if isinstance(prefs[k], list):
            prefs[k] = prefs[k][-30:]
    return cards
