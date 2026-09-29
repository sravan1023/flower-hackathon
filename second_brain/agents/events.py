"""Events agent: discover -> rank vs goal -> cards -> (approved) RSVP brief."""

from __future__ import annotations

from typing import Any

from .. import cards as cardlib
from .. import goal_engine


def run(agent: Any, session: dict, profile: dict, start_id: int) -> list[dict]:
    goal = session["goal"]
    events = goal_engine.discover_events(agent, goal["goal"], profile)
    texts = [f"{e['title']}. {e.get('summary', '')}" for e in events]
    scores, backend = goal_engine.rank(goal["goal"], texts, profile)
    ranked = sorted(zip(events, scores), key=lambda p: -p[1])
    top, rest = ranked[:3], ranked[3:]
    out = []
    for i, (e, s) in enumerate(top):
        others = [(x, y) for x, y in ranked if x is not e][:3]
        alts = [{"title": f"{x['title']} ({x['date']})", "score": y, "detail": x.get("url", ""), "item": {"text": f"{x['title']}. {x.get('summary', '')}", "url": x.get("url", ""), "date": x["date"]}} for x, y in others]
        out.append(cardlib.make_card(
            start_id + i, "events", f"{e['title']} ({e['date']})", s, f"{e.get('summary', '')[:80]} [{backend}]", alts,
            {"text": f"{e['title']}. {e.get('summary', '')}", "hours": 3, "kind": "rsvp", "url": e.get("url", ""), "date": e["date"]},
            detail=e.get("url", "")))
    return out
