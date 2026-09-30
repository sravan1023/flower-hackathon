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
        v = int(h) + int(m) / 60
        return v if 0 <= int(h) <= 24 and 0 <= int(m) < 60 else default
    except (ValueError, TypeError):
        return default


def constraints_state(profile: dict, today: date | None = None) -> dict:
    c = profile.get("constraints", {})
    c = c if isinstance(c, dict) else {}
    try:
        need = float(c.get("sleep_min_hours", 7))
    except (TypeError, ValueError):
        need = 7.0
    today = today or date.today()
    recent = {today.isoformat(), (today - timedelta(days=1)).isoformat()}  # stale sleep logs must not lighten today's plan
    sleeps = []
    for e in profile.get("health_log", []):
        try:
            if e.get("kind") == "sleep_hours" and str(e.get("date", "")) in recent:
                sleeps.append(float(e["value"]))
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    tired = bool(sleeps) and sleeps[-1] < need
    return {"latest_end": _hhmm(c.get("no_events_after", "21:00")), "tired": tired, "need": need}


def blocks(goal: dict, profile: dict, day: date) -> list[dict]:
    st = constraints_state(profile)
    topic = str((profile.get("topics") or [goal["goal"][:30]])[0])
    out, taken = [], []
    for tpl, hours, start_h in TEMPLATES:
        if st["tired"]:
            hours, start_h = min(hours, 1.0), max(start_h, 10)
        if start_h + hours > st["latest_end"]:
            start_h = st["latest_end"] - hours
        if start_h < 6:
            continue
        if any(start_h < e_end and start_h + hours > e_start for e_start, e_end in taken):  # no overlapping blocks
            continue
        taken.append((start_h, start_h + hours))
        start = datetime(day.year, day.month, day.day) + timedelta(hours=start_h)
        out.append({"title": tpl.format(t=topic, g=goal["goal"][:40]), "hours": hours, "start": start.isoformat(timespec="minutes")})
    return out


def run(session: dict, profile: dict, start_id: int, day: date | None = None, week: bool = False) -> list[dict]:
    if week:
        return week_run(session, profile, start_id, day)
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
        alts = [{"title": f"{x['title']} @ {x['start'][11:16]}", "score": y, "detail": x["start"], "item": {"text": x["title"], "hours": x["hours"], "start": x["start"], "date": x["start"][:10]}} for x, y in others]
        out.append(cardlib.make_card(
            start_id + i, "planner", f"{b['title']} {b['start'][:10]} {b['start'][11:16]} ({b['hours']:g}h)", s,
            f"goal-aligned, ends before {int(st['latest_end']):02d}:{int(round(st['latest_end'] % 1 * 60)):02d}{note} [{backend}]", alts,
            {"text": b["title"], "hours": b["hours"], "kind": "calendar", "start": b["start"], "date": b["start"][:10]}))
    return out


# ---- week mode: next 7 days (tomorrow..+7), 1-3 blocks/day, at most 12 cards, two alternative slots each ----
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_WEEK_CARDS = 12


def _gym_per_week(profile: dict) -> int:
    c = profile.get("constraints", {})
    for k, v in (c.items() if isinstance(c, dict) else []):
        if any(w in str(k).lower() for w in ("gym", "workout", "exercise")):
            try:
                return max(0, min(6, int(float(v))))
            except (TypeError, ValueError):
                pass
    return 3


def _free(occ: list, s: float, h: float, lo: float, hi: float) -> bool:
    return lo <= s and s + h <= hi and not any(s < e and s + h > b for b, e in occ)


def _place(occ: list, h: float, prefs: list, lo: float, hi: float, avoid: float | None = None) -> float | None:
    cands = list(prefs) + [x / 2 for x in range(int(lo * 2), int(hi * 2))]
    for s in cands:
        if s != avoid and _free(occ, s, h, lo, hi):
            return float(s)
    return None


def _iso(d: date, h: float) -> str:
    return (datetime(d.year, d.month, d.day) + timedelta(hours=h)).isoformat(timespec="minutes")


def _tag(d: date, h: float) -> str:
    return f"{_DAYS[d.weekday()]} {int(h):02d}:{int(round(h % 1 * 60)):02d}"


def week_run(session: dict, profile: dict, start_id: int, today: date | None = None) -> list[dict]:
    goal = session["goal"]
    today = today or date.today()
    st = constraints_state(profile, today)
    hi, lo = st["latest_end"], 7.0
    topic = str((profile.get("topics") or [goal["goal"][:20]])[0])[:18]
    ms = [str(m.get("title", m) if isinstance(m, dict) else m)[:80] for m in (session.get("milestones") or [])] or [goal["goal"][:80]]
    # (kind, label, hours, preferred start hours)
    kinds = {
        "study": (f"{topic} lab", 1.5, [18, 19, 17, 8]),
        "gym": ("Gym", 1.0, [7, 17.5, 12]),
        "prep": (f"Event prep: {topic}", 1.0, [12, 13, 16]),
        "outreach": ("Outreach", 1.0, [15, 14, 16]),
    }
    gym_n = _gym_per_week(profile)
    gym_days = {round(i * 7 / gym_n) if gym_n else 99 for i in range(gym_n)} if gym_n else set()
    occ: dict[int, list] = {i: [] for i in range(1, 8)}
    cand = []
    for k in range(1, 8):
        d = today + timedelta(days=k)
        order = ["study"] + (["gym"] if (k - 1) in gym_days else []) + (["prep"] if k % 2 == 1 else []) + (["outreach"] if k % 3 == 2 else [])
        for kind in order[:3]:
            label, h, prefs = kinds[kind]
            if k == 1 and st["tired"]:
                if kind == "gym":
                    continue
                h, prefs = min(h, 1.0), [max(p, 10) for p in prefs]
            s = _place(occ[k], h, prefs, lo, hi)
            if s is None:
                continue
            occ[k].append((s, s + h))
            cand.append({"k": k, "d": d, "kind": kind, "label": label, "hours": h, "start": s})
    if not cand:
        return []
    titles = [f"{_tag(c['d'], c['start'])} {c['label']}"[:50] for c in cand]
    scores, backend = goal_engine.rank(goal["goal"], titles, profile)
    order = sorted(range(len(cand)), key=lambda i: -scores[i])[:MAX_WEEK_CARDS]
    keep = sorted(order, key=lambda i: (cand[i]["k"], cand[i]["start"]))
    kept_occ: dict[int, list] = {i: [] for i in range(1, 8)}
    for i in keep:
        kept_occ[cand[i]["k"]].append((cand[i]["start"], cand[i]["start"] + cand[i]["hours"]))
    out = []
    for n, i in enumerate(keep):
        c = cand[i]
        label, h, prefs = kinds[c["kind"]][0], c["hours"], kinds[c["kind"]][2]
        alts, used = [], {(c["k"], c["start"])}
        for dk in (1, 2, -1, 3, -2):  # nearby days first: a = different day
            k2 = c["k"] + dk
            if k2 not in kept_occ or len(alts) >= 2:
                continue
            s2 = _place(kept_occ[k2], h, prefs, lo, hi)
            if s2 is None or (k2, s2) in used:
                continue
            used.add((k2, s2))
            d2 = today + timedelta(days=k2)
            alts.append({"title": f"{_tag(d2, s2)} {label}"[:50], "score": scores[i] * 0.95, "detail": _iso(d2, s2), "item": {"text": label, "hours": h, "start": _iso(d2, s2), "date": _iso(d2, s2)[:10], "milestone": ms[n % len(ms)]}})
        ms_t = ms[n % len(ms)]
        item = {"text": label, "hours": h, "kind": "calendar", "start": _iso(c["d"], c["start"]), "date": _iso(c["d"], c["start"])[:10], "milestone": ms_t}
        out.append(cardlib.make_card(start_id + n, "planner", titles[i], scores[i], f"{c['kind']} block for milestone '{ms_t[:60]}' [{backend}]", alts, item))
    return out
