"""Planner agent: goal-aligned calendar blocks for tomorrow, respecting profile constraints and health_log."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .. import cards as cardlib
from .. import goal_engine

# (title template, hours, preferred start hour)
TEMPLATES = [
    ("Deep work: {t} project", 2.0, 9),
    ("Study block: {t} reading and notes", 1.5, 8),
    ("Apply and network for: {g}", 1.5, 14),
    ("Build a public write-up on {t}", 1.0, 16),
    ("Evening reading on {t}", 1.0, 19),
]


def _hhmm(s: str, default: float = 21.0) -> float:
    try:
        h, m = str(s).split(":")
        return int(h) + int(m) / 60
    except (ValueError, TypeError):
        return default


def constraints_state(profile: dict) -> dict:
    c = profile.get("constraints", {}) or {}
    need = float(c.get("sleep_min_hours", 7))
    sleeps = [e["value"] for e in profile.get("health_log", []) if e.get("kind") == "sleep_hours"]
    tired = bool(sleeps) and sleeps[-1] < need
    return {"latest_end": _hhmm(c.get("no_events_after", "21:00")), "tired": tired, "need": need}


def blocks(goal: dict, profile: dict, day: date) -> list[dict]:
    st = constraints_state(profile)
    topic = (profile.get("topics") or [goal["goal"][:30]])[0]
    out = []
    for tpl, hours, start_h in TEMPLATES:
        if st["tired"]:
            hours, start_h = min(hours, 1.0), max(start_h, 10)
        if start_h + hours > st["latest_end"]:
            start_h = st["latest_end"] - hours
        if start_h < 6:
            continue
        start = datetime(day.year, day.month, day.day) + timedelta(hours=start_h)
        out.append({"title": tpl.format(t=topic, g=goal["goal"][:40]), "hours": hours, "start": start.isoformat(timespec="minutes")})
    return out


def run(session: dict, profile: dict, start_id: int, day: date | None = None) -> list[dict]:
    goal = session["goal"]
    day = day or (date.today() + timedelta(days=1))
    cand = blocks(goal, profile, day)
    if not cand:
        return []
    scores, backend = goal_engine.rank(goal["goal"], [b["title"] for b in cand], profile)
    ranked = sorted(zip(cand, scores), key=lambda p: -p[1])
    st = constraints_state(profile)
    note = " (lighter: short sleep logged)" if st["tired"] else ""
    out = []
    for i, (b, s) in enumerate(ranked[:2]):
        others = [(x, y) for x, y in ranked if x is not b][:3]
        alts = [{"title": f"{x['title']} @ {x['start'][11:16]}", "score": y, "detail": x["start"]} for x, y in others]
        out.append(cardlib.make_card(
            start_id + i, "planner", f"{b['title']} {b['start'][:10]} {b['start'][11:16]} ({b['hours']:g}h)", s,
            f"goal-aligned, ends before {int(st['latest_end'])}:00{note} [{backend}]", alts,
            {"text": b["title"], "hours": b["hours"], "kind": "calendar", "start": b["start"], "date": b["start"][:10]}))
    return out
